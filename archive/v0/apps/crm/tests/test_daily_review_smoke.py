"""仅冒烟验证新增 MCP 查询和每日事件的关键路径。"""

import base64
import json
import sqlite3
from datetime import datetime

import pytest
from mcp_platform import RuntimeConfig
from mcp_platform.events import EventError, EventService, WebhookResponse

from personal_crm.app.settings import Settings
from personal_crm.daily_review import DailyReviewService
from personal_crm.daily_review_events import EVENT_NAMES, DailyReviewEventProducer
from personal_crm.events import EVENT_NAME, ChatEventProducer
from personal_crm.mcp import create_mcp
from personal_crm.archive import Archive


def at(value):
    return datetime.fromisoformat(value + "+08:00")


def sources(tmp_path):
    directory = tmp_path / "skysight"
    directory.mkdir()
    body = "## Memory summary\n完整原文🙂\n" + "长记录\n" * 2000
    for name in (
        "2026-10-04T16-00-00-test-6h-memory-summary.md",
        "2026-10-04T16-10-00-test-10min-memory-summary.md",
        "2026-10-05T02-00-00-test-10min-memory-summary.md",
    ):
        (directory / name).write_text(body, encoding="utf-8")
    database = tmp_path / "memos.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE memo (id INTEGER, uid TEXT, creator_id INTEGER, row_status TEXT, "
            "created_ts INTEGER, updated_ts INTEGER, content TEXT)"
        )
        for i, owner, status, content in (
            (1, 1, "NORMAL", "#日报 2026-10-05\n今天的 Hermes 日报"),
            (2, 1, "NORMAL", "#日报 2026-10-04\n昨日补写"),
            (3, 2, "NORMAL", "#日报 2026-10-05\n其他作者"),
            (4, 1, "ARCHIVED", "#日报 2026-10-05\n已归档"),
            (5, 1, "NORMAL", "普通 Memo 引用了 #日报 2026-10-05"),
        ):
            connection.execute(
                "INSERT INTO memo VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    i,
                    f"memo-{i}",
                    owner,
                    status,
                    int(at("2026-10-06T08:00").timestamp()),
                    int(at("2026-10-06T08:00").timestamp()),
                    content,
                ),
            )
    service = DailyReviewService(
        skylight_path=str(directory),
        memos_database_path=str(database),
        clock=lambda: at("2026-10-05T00:01"),
    )
    return service, directory, body


@pytest.mark.asyncio
async def test_mcp_default_today_business_date_and_full_content(tmp_path):
    daily, _, body = sources(tmp_path)
    server = create_mcp(
        Archive(asset_root=tmp_path / "assets"),
        Settings(mcp_development_no_auth=True),
        daily_reviews=daily,
    )
    result = await server.call_tool("get_daily_codex_skylight", {}, run_middleware=False)
    page = result.structured_content
    assert page["date"] == "2026-10-05"
    assert page["total_count"] == 2  # 6h + 未覆盖的 10min，按北京时间归日。
    record = page["records"][0]
    tail = await server.call_tool(
        record["content_read_tool"], record["content_read_arguments"], run_middleware=False
    )
    assert record["content"] + tail.structured_content["content"] == body
    memos = await server.call_tool("get_daily_memos_report", {}, run_middleware=False)
    assert memos.structured_content["total_count"] == 1
    assert memos.structured_content["records"][0]["id"] == "memos/memo-1"
    assert memos.structured_content["records"][0]["created_at"].startswith("2026-10-06")
    empty = await server.call_tool(
        "get_daily_memos_report", {"day": "2026-10-07"}, run_middleware=False
    )
    assert empty.structured_content["empty_day"] is True


@pytest.mark.asyncio
async def test_daily_events_coexist_retry_snapshot_and_signed_delivery(tmp_path):
    daily, directory, body = sources(tmp_path)

    class Callback:
        def __init__(self):
            self.posts = []

        async def post(self, url, payload, headers):
            value = json.loads(payload)
            self.posts.append((value, headers))
            if value.get("type") == "verification":
                return WebhookResponse(200, json.dumps({"challenge": value["challenge"]}).encode())
            return WebhookResponse(202, b"{}")

    callback = Callback()
    config = RuntimeConfig(
        name="daily-review-smoke",
        authorized_usernames={"owner", "other"},
        public_base_url="https://crm.example.com",
        oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
        oidc_client_id="test",
        oidc_client_secret="synthetic-secret",
        storage_path=str(tmp_path / "oauth"),
        storage_encryption_key="s" * 32,
        jwt_signing_key="j" * 32,
    )
    bus = EventService(
        config,
        storage_path=str(tmp_path / "events"),
        transport=callback,
        clock=lambda: at("2026-10-05T23:00").timestamp(),
    )
    repo = Archive(asset_root=tmp_path / "assets")
    ChatEventProducer(repo, bus, owner="owner", storage_path=str(tmp_path / "chat"))
    producers = {
        source: DailyReviewEventProducer(
            daily, bus, source=source, owner="owner", storage_path=str(tmp_path / "reports")
        )
        for source in EVENT_NAMES
    }
    assert {event["name"] for event in bus.list_events("owner")["events"]} == {
        EVENT_NAME,
        *EVENT_NAMES.values(),
    }
    assert bus.list_events("other")["events"] == []
    for source, producer in producers.items():
        await bus.subscribe(
            "owner",
            {
                "name": EVENT_NAMES[source],
                "arguments": {},
                "delivery": {
                    "mode": "webhook",
                    "url": "https://callback.example.com/events",
                    "secret": "whsec_"
                    + base64.b64encode(b"synthetic-webhook-secret-32-bytes").decode(),
                },
            },
        )
        assert await producer.run_once(at("2026-10-05T22:59")) is None
    with pytest.raises(EventError):
        await bus.subscribe(
            "other",
            {
                "name": EVENT_NAMES["memos"],
                "arguments": {},
                "delivery": {},
            },
        )

    skylight = producers["codex_skylight"]
    original_publish = bus.publish

    async def fail(*args, **kwargs):
        raise ConnectionError("synthetic queue failure")

    bus.publish = fail
    with pytest.raises(ConnectionError):
        await skylight.run_once(at("2026-10-05T23:00"))
    for path in directory.iterdir():
        path.write_text("上游后来更新", encoding="utf-8")
    bus.publish = original_publish
    result = await skylight.run_once(at("2026-10-05T23:01"))
    report = skylight.read_page(result["report_id"], subject="owner")
    record = report["records"][0]
    tail = skylight.read_content(result["report_id"], record["id"], subject="owner", offset=4000)
    assert record["content"] + tail["content"] == body
    with pytest.raises(PermissionError):
        skylight.read_page(result["report_id"], subject="other")
    await producers["memos"].run_once(at("2026-10-05T23:01"))
    # 重建总线模拟进程重启，保留源快照和事件投递队列。
    reopened_bus = EventService(
        config, storage_path=str(tmp_path / "events"), transport=callback, clock=bus.clock
    )
    reopened = {
        source: DailyReviewEventProducer(
            daily,
            reopened_bus,
            source=source,
            owner="owner",
            storage_path=str(tmp_path / "reports"),
        )
        for source in EVENT_NAMES
    }
    restarted = reopened["codex_skylight"]
    assert await restarted.run_once(at("2026-10-05T23:02")) is None
    assert (await reopened_bus.run_delivery_once())["accepted"] == 2
    events = [value for value, _ in callback.posts if value.get("type") != "verification"]
    assert {value["name"] for value in events} == set(EVENT_NAMES.values())
    assert body not in json.dumps(events, ensure_ascii=False)
    assert all("webhook-signature" in headers for _, headers in callback.posts)
