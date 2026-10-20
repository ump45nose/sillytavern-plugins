import base64

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.mcp import _auth_check, create_mcp

from .test_archive import msg


def settings(**kw):
    return Settings(
        mcp_development_no_auth=True,
        crm_api_token="write",
        crm_viewer_token="read",
        wechat_webhook_secret="collector",
        **kw,
    )


def test_http_permissions_crud_ingest_attachments(archive):
    with TestClient(create_app(settings(), archive)) as c:
        url = "/api/v1/crm"
        assert c.get(url + "/people").status_code == 401
        readonly = {"Authorization": "Bearer read"}
        write = {"Authorization": "Bearer write"}
        assert c.post(url + "/people", headers=readonly, json={"name": "A"}).status_code == 401
        p = c.post(url + "/people", headers=write, json={"name": "A"}).json()
        assert c.get(url + "/people", headers=readonly).json()["items"][0]["id"] == p["id"]
        assert (
            c.patch(url + "/people/" + p["id"], headers=write, json={"notes": "hi"}).json()["name"]
            == "A"
        )
        assert c.post(url + "/ingest/wechat", json={"messages": [msg()]}).status_code == 401
        assert (
            c.post(
                url + "/ingest/wechat",
                headers={"X-Webhook-Token": "collector"},
                json={"messages": [msg()]},
            ).json()["accepted"]
            == 1
        )
        row = c.post(
            url + "/interactions",
            headers=write,
            json={"person_ids": [p["id"]], "date": "2026-10-15", "content": "正文"},
        ).json()
        assert (
            c.get(url + "/interactions/" + row["id"], headers=readonly).json()["content"] == "正文"
        )
        file = c.post(
            url + "/attachments", headers=write, files={"file": ("x.txt", b"file", "text/plain")}
        ).json()
        assert (
            c.get(url + "/attachments/" + file["id"] + "/content", headers=readonly).content
            == b"file"
        )
        assert (
            c.patch(
                url + "/interactions/" + row["id"],
                headers=write,
                json={"attachment_ids": [file["id"]]},
            ).status_code
            == 200
        )
        assert c.delete(url + "/interactions/" + row["id"], headers=write).status_code == 200
        assert c.get(url + "/interactions/" + row["id"], headers=readonly).status_code == 404
        assert c.get(url + "/interactions?cursor=!", headers=readonly).status_code == 422
        assert (
            c.patch(url + "/people/" + p["id"], headers=write, json={"name": None}).status_code
            == 422
        )
        assert c.post("/api/v1/webhooks/wechat", json={}).status_code == 404


@pytest.mark.asyncio
async def test_mcp_tools_crud_and_content_continuation(archive):
    async with Client(create_mcp(archive, settings())) as client:
        names = {x.name for x in await client.list_tools()}
        assert names == {
            "list_people",
            "get_person",
            "create_person",
            "update_person",
            "delete_person",
            "merge_people",
            "bind_person_identity",
            "list_interactions",
            "get_interaction",
            "create_interaction",
            "update_interaction",
            "delete_interaction",
            "upload_attachment",
            "read_attachment",
        }
        assert not names & {"list_facts", "list_reminders", "get_weekly_metrics", "search_people"}
        person = (await client.call_tool("create_person", {"data": {"name": "张三"}})).data
        interaction = (
            await client.call_tool(
                "create_interaction",
                {
                    "data": {
                        "person_ids": [person["id"]],
                        "date": "2026-10-15",
                        "content": "中文" * 10000,
                    }
                },
            )
        ).data
        first = (
            await client.call_tool("get_interaction", {"interaction_id": interaction["id"]})
        ).data
        second = (
            await client.call_tool(
                "get_interaction",
                {"interaction_id": interaction["id"], "offset_chars": first["next_offset_chars"]},
            )
        ).data
        assert first["content"] + second["content"] == "中文" * 10000
        assert second["next_offset_chars"] is None
        await client.call_tool(
            "update_interaction",
            {"interaction_id": interaction["id"], "changes": {"content": "修改"}},
        )
        assert archive.get_interaction(interaction["id"])["content"] == "修改"
        file = (
            await client.call_tool(
                "upload_attachment",
                {"name": "x", "media_type": "text/plain", "content_base64": "YWJj"},
            )
        ).data
        got = (await client.call_tool("read_attachment", {"attachment_id": file["id"]})).data
        assert base64.b64decode(got["base64"]) == b"abc"


def test_mcp_readonly_auth_unchanged():
    from types import SimpleNamespace

    s = Settings(
        oidc_authorized_usernames="owner,reader",
        oidc_read_only_usernames="reader",
        public_base_url="https://crm.example.com",
        oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
        oidc_client_id="crm",
        oidc_client_secret="secret",
        oauth_jwt_signing_key="j" * 32,
        oauth_storage_encryption_key="e" * 32,
    )

    def token(user):
        return SimpleNamespace(token=SimpleNamespace(claims={"preferred_username": user}))

    read, write = _auth_check(s, write=False), _auth_check(s, write=True)
    assert read(token("reader")) and not write(token("reader"))
    assert read(token("owner")) and write(token("owner"))
    assert not read(token("stranger")) and not write(token("stranger"))
