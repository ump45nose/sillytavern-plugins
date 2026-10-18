import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from personal_crm.archive.models import messages
from personal_crm.archive.service import Conflict, NotFound


def msg(key="1", at="2026-10-15T10:00:00+08:00", **kw):
    return dict(key=key, account="me", peer="you", name="小王", sent_at=at, content="原文", **kw)


def test_people_patch_search_and_same_names(archive):
    p = archive.create_person(
        dict(
            name="小王",
            aliases=["王", "王"],
            tags=["朋友"],
            contacts=[dict(type="phone", value="123")],
        )
    )
    q = archive.create_person(dict(name="小王"))
    assert p["id"] != q["id"] and p["aliases"] == ["王"]
    assert archive.list_people(query="123")["items"][0]["id"] == p["id"]
    assert archive.list_people(tag="朋友")["items"][0]["id"] == p["id"]
    assert not archive.list_people(tag="朋")["items"]
    edited = archive.update_person(p["id"], {"notes": "备注", "relationship": "朋友"})
    assert edited["contacts"] == p["contacts"]
    edited = archive.update_person(p["id"], {"notes": None, "tags": None, "relationship": None})
    assert edited["notes"] == "" and edited["tags"] == [] and edited["relationship"] is None
    with pytest.raises(ValueError):
        archive.update_person(p["id"], {"name": None})


def test_shared_interaction_merge_delete(archive):
    a, b, c = [archive.create_person({"name": x}) for x in ["张三", "李四", "张三2"]]
    row = archive.create_interaction(
        dict(
            person_ids=[a["id"], b["id"], a["id"]], date="2026-10-15", content="我、张三、李四吃饭"
        )
    )
    assert len(row["person_ids"]) == 2
    assert len(archive.list_interactions()["items"]) == 1
    assert len(archive.list_interactions(person_id=b["id"])["items"]) == 1
    archive.update_interaction(row["id"], {"content": "编辑一次"})
    assert archive.get_interaction(row["id"])["content"] == "编辑一次"
    archive.merge_people(a["id"], c["id"])
    assert set(archive.get_interaction(row["id"])["person_ids"]) == {b["id"], c["id"]}
    archive.delete_person(c["id"])
    assert archive.get_interaction(row["id"])["person_ids"] == [b["id"]]
    archive.delete_person(b["id"])
    with pytest.raises(NotFound):
        archive.get_interaction(row["id"])


def test_private_identity_bind_rebind_and_merge(archive):
    archive.ingest_wechat({"messages": [msg()]})
    first = archive.list_people()["items"][0]
    second = archive.create_person({"name": "改正"})
    archive.bind_person_identity(second["id"], dict(account="me", external_id="you"))
    assert archive.list_interactions()["items"][0]["person_ids"] == [second["id"]]
    archive.ingest_wechat({"messages": [msg("2", "2026-10-15T10:01:00+08:00")]})
    assert len(archive.list_interactions()["items"]) == 1
    assert archive.get_person(second["id"])["name"] == "改正"
    archive.merge_people(first["id"], second["id"])
    assert len(archive.list_people()["items"]) == 1


def test_gap_boundaries_edit_append_and_duplicates(archive):
    rows = [
        msg("a"),
        msg("b", "2026-10-15T10:30:00+08:00", is_self=True),
        msg("c", "2026-10-15T11:00:01+08:00"),
    ]
    result = archive.ingest_wechat({"messages": rows[::-1]})
    assert result["accepted"] == 3
    items = archive.list_interactions()["items"]
    assert len(items) == 2
    old = items[-1]["id"]
    archive.update_interaction(old, {"content": "人工修改"})
    archive.ingest_wechat({"messages": [msg("d", "2026-10-15T10:31:00+08:00")]})
    assert archive.get_interaction(old)["content"].startswith("人工修改\n10:31")
    assert archive.ingest_wechat({"messages": rows})["duplicates"] == 3
    assert len(archive.list_interactions()["items"]) == 2
    archive.delete_interaction(old)
    assert archive.ingest_wechat({"messages": [rows[0]]})["duplicates"] == 1
    with pytest.raises(NotFound):
        archive.get_interaction(old)


def test_midnight_dates_accounts_and_gap_change(archive):
    archive.ingest_wechat({"messages": [msg("a", "2026-10-14T23:56:00+08:00")]})
    archive.ingest_wechat({"messages": [msg("b", "2026-10-15T00:09:00+08:00")]})
    row = archive.list_interactions()["items"][0]
    assert row["date"] == date(2026, 10, 14)
    assert len(archive.list_interactions(start="2026-10-15", end="2026-10-15")["items"]) == 1
    assert "2026-10-15 00:09" in archive.get_interaction(row["id"])["content"]
    other = msg("other")
    other["account"] = "second-account"
    archive.ingest_wechat({"messages": [other]})
    assert len(archive.list_people()["items"]) == 2
    archive.gap = __import__("datetime").timedelta(minutes=5)
    archive.ingest_wechat({"messages": [msg("c", "2026-10-15T00:15:00+08:00")]})
    assert len(archive.list_interactions()["items"]) == 3


def test_content_date_validation_and_rollback(archive):
    a = archive.create_person({"name": "A"})
    with pytest.raises(NotFound):
        archive.create_interaction(dict(person_ids=["missing"], date="2026-10-15", content="x"))
    assert not archive.list_interactions()["items"]
    for fields in [
        dict(started_at="2026-10-15T10:00:00"),
        dict(ended_at="2026-10-15T10:00:00+08:00"),
    ]:
        with pytest.raises(ValueError):
            archive.create_interaction(dict(person_ids=[a["id"]], date="2026-10-15", **fields))
    with pytest.raises(ValidationError):
        archive.ingest_wechat({"messages": [dict(msg(), peer="123@chatroom")]})
    assert len(archive.list_people()["items"]) == 1


def test_cursor_dates_nulls_and_unicode(archive):
    a, b = [archive.create_person({"name": n, "tags": ["朋友"]}) for n in ["甲", "乙"]]
    for data in [
        dict(date="2026-10-15"),
        dict(date="2026-10-15", started_at="2026-10-15T10:00:00+08:00"),
        dict(date="2026-10-14"),
    ]:
        archive.create_interaction(dict(person_ids=[a["id"]], content="中文正文", **data))
    cursor = None
    ids = []
    while True:
        page = archive.list_interactions(query="中文", limit=1, cursor=cursor)
        ids.extend(x["id"] for x in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(ids) == len(set(ids)) == 3
    first = archive.list_people(limit=1)
    assert first["items"][0]["id"] == a["id"]
    assert archive.list_people(limit=1, cursor=first["next_cursor"])["items"][0]["id"] == b["id"]
    for cursor in ["!", base64.b64encode(b"{}").decode()]:
        with pytest.raises(ValueError):
            archive.list_interactions(cursor=cursor)


def test_attachments_edit_late_upload_chunk_and_delete(archive):
    archive.ingest_wechat(
        {"messages": [msg(attachment={"name": "图片", "media_type": "image/png"})]}
    )
    row = archive.get_interaction(archive.list_interactions()["items"][0]["id"])
    aid = row["attachment_ids"][0]
    assert f"attachment://{aid}" in row["content"]
    assert archive.read_attachment(aid)["available"] is False
    archive.update_interaction(row["id"], {"content": "可编辑引用"})
    data = b"picture"
    import hashlib

    assert (
        archive.attach_wechat_media(
            "1", [data], "picture.png", "image/png", hashlib.sha256(data).hexdigest()
        )["status"]
        == "attached"
    )
    assert base64.b64decode(archive.read_attachment(aid)["base64"]) == data
    assert archive.get_interaction(row["id"])["content"] == "可编辑引用"
    chunk = archive.upload_attachment_chunk("a.txt", "text/plain", "YWJj", final=False)
    with pytest.raises(Conflict):
        archive.upload_attachment_chunk(
            "a.txt", "text/plain", "ZA==", attachment_id=chunk["id"], offset_bytes=0
        )
    done = archive.upload_attachment_chunk(
        "a.txt", "text/plain", "ZA==", attachment_id=chunk["id"], offset_bytes=3
    )
    assert base64.b64decode(archive.read_attachment(done["id"])["base64"]) == b"abcd"
    archive.delete_interaction(row["id"])
    assert (
        archive.attach_wechat_media(
            "1", [data], "picture.png", "image/png", hashlib.sha256(data).hexdigest()
        )["status"]
        == "deleted"
    )


def test_concurrent_append_and_edit(archive):
    archive.ingest_wechat({"messages": [msg()]})
    iid = archive.list_interactions()["items"][0]["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda n: archive.ingest_wechat(
                    {"messages": [msg(str(n), "2026-10-15T10:01:00+08:00")]}
                ),
                range(2, 12),
            )
        )
    assert archive.get_interaction(iid)["content"].count("\n") == 10
    with archive.engine.connect() as c:
        assert c.scalar(select(func.count()).select_from(messages)) == 11


def test_people_recency_uses_end_of_cross_day_interaction(archive):
    archive.ingest_wechat(
        {"messages": [msg("a", "2026-10-14T23:56:00+08:00"), msg("b", "2026-10-15T00:09:00+08:00")]}
    )
    first = archive.list_people()["items"][0]
    other = archive.create_person({"name": "其他人"})
    archive.create_interaction(
        {
            "person_ids": [other["id"]],
            "date": "2026-10-15",
            "started_at": "2026-10-15T00:02:00+08:00",
            "content": "另一事件",
        }
    )
    page = archive.list_people(limit=1)
    assert page["items"][0]["id"] == first["id"]
    assert page["items"][0]["last_interaction_date"] == date(2026, 10, 15)
    assert archive.get_person(first["id"])["last_interaction_date"] == date(2026, 10, 15)
    assert archive.list_people(limit=1, cursor=page["next_cursor"])["items"][0]["id"] == other["id"]


def test_exact_time_controls_business_date_and_patch(archive):
    person = archive.create_person({"name": "小王"})
    row = archive.create_interaction(
        dict(person_ids=[person["id"]], date="2026-10-01", started_at="2026-10-16T00:05:00+08:00")
    )
    assert str(row["date"]) == "2026-10-16"
    assert archive.list_interactions(start="2026-10-16", end="2026-10-16")["items"]
    archive.update_interaction(row["id"], {"started_at": "2026-10-17T01:00:00+08:00"})
    assert str(archive.get_interaction(row["id"])["date"]) == "2026-10-17"


def test_media_receipt_and_reject_encrypted_cache(archive):
    row = dict(msg(), attachment={"name": "图片"})
    result = archive.ingest_wechat({"messages": [row]})
    assert result["missing_media_keys"] == [row["key"]]
    with pytest.raises(ValueError, match="must_be_decoded"):
        archive.attach_wechat_media(
            row["key"], [b"encrypted"], "image.dat", "application/vnd.wechat.encrypted-image", None
        )
    archive.attach_wechat_media(row["key"], [b"file"], "image.png", "image/png", None)
    assert archive.ingest_wechat({"messages": [row]})["missing_media_keys"] == []
    iid = archive.list_interactions()["items"][0]["id"]
    archive.delete_interaction(iid)
    assert (
        archive.ingest_wechat({"messages": [row], "pending_media_keys": [row["key"]]})[
            "missing_media_keys"
        ]
        == []
    )


@pytest.mark.asyncio
async def test_modern_mcp_tools_without_events(archive):
    import httpx

    from personal_crm.app.server import create_app
    from personal_crm.app.settings import Settings

    archive.create_person(dict(name="协议测试"))
    app = create_app(Settings(mcp_development_no_auth=True), archive)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost"
        ) as client:
            version = "2026-07-28"
            meta = {
                "io.modelcontextprotocol/protocolVersion": version,
                "io.modelcontextprotocol/clientCapabilities": {},
            }

            async def call(method, params):
                return await client.post(
                    "/mcp",
                    headers={
                        "mcp-protocol-version": version,
                        "mcp-method": method,
                        "mcp-name": params.get("name", ""),
                        "Accept": "application/json, text/event-stream",
                    },
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": method,
                        "params": dict(params, _meta=meta),
                    },
                )

            discover = await call("server/discover", {})
            assert discover.json()["result"]["capabilities"] == {"tools": {}}
            tools = await call("tools/list", {})
            assert tools.status_code == 200
            import json

            result = json.loads(
                next(s[6:] for s in tools.text.splitlines() if s.startswith("data: "))
            )["result"]
            assert len(result["tools"]) == 14
            result = await call("tools/call", {"name": "list_people", "arguments": {}})
            assert "协议测试" in result.text
            assert '"resultType":"complete"' in result.text
