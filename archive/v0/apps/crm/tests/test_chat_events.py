"""每日聊天事件的窗口、全文、补发、重启与所有者隔离。"""

import json
from datetime import datetime

import pytest
from fastmcp.exceptions import ToolError

from personal_crm.app.settings import Settings
from personal_crm.core import CrmService
from personal_crm.events import EVENT_NAME, ChatEventProducer
from personal_crm.mcp import create_mcp
from personal_crm.storage import CrmRepository
from personal_crm.storage.models import Interaction


def at(value):
    return datetime.fromisoformat(value + "+08:00")


class EventSink:
    def __init__(self):
        self.events = []
        self.fail = False
        self.subject = "owner-a"
        self.definitions = []

    def register_event(self, *definition, **options):
        self.definitions.append((definition, options))

    def authenticated_subject(self):
        return self.subject

    async def publish(self, name, data, **arguments):
        if self.fail:
            raise ConnectionError("simulated persistence failure")
        self.events.append({"name": name, "data": data, **arguments})
        return {"event_id": arguments["event_id"], "queued": 1, "duplicate": False}


def setup(tmp_path):
    repo = CrmRepository("sqlite:///:memory:")
    service = CrmService(repo)
    person = service.create_person("测试联系人")
    sink = EventSink()
    producer = ChatEventProducer(
        repo, sink, owner="owner-a", storage_path=str(tmp_path / "reports")
    )
    return repo, service, person, sink, producer


def add(service, person, moment, content="原始消息", direction="inbound", raw=True):
    row, *_ = service.record_interaction(
        person_id=person.id,
        occurred_at=at(moment),
        direction=direction,
        channel="wechat",
        summary=("消息内容：" if raw else "") + content,
    )
    return row


@pytest.mark.asyncio
async def test_full_messages_only_at_local_2300_and_metadata_event(tmp_path):
    _, service, person, sink, producer = setup(tmp_path)
    add(service, person, "2026-10-04T12:00", "历史基线")
    body = "第一行\n第二行🙂"
    add(service, person, "2026-10-05T08:01", body)
    add(service, person, "2026-10-05T09:02", "完整回复", "outbound")
    assert await producer.run_once(at("2026-10-05T22:59:59")) is None
    result = await producer.run_once(at("2026-10-05T23:00:05"))
    metadata = sink.events[0]["data"]
    assert sink.events[0]["name"] == EVENT_NAME
    assert sink.events[0]["subject"] == "owner-a"
    assert body not in json.dumps(sink.events, ensure_ascii=False)
    assert metadata["window_start"] == "2026-10-05T00:00:00+08:00"
    assert metadata["window_end"] == "2026-10-05T23:00:05+08:00"
    assert metadata["daily_count"] == 2
    assert metadata["supplemental_count"] == 0
    assert metadata["coverage"]["pending_windows"][-1]["reason"] == "after_daily_cutoff"
    page = producer.read_page(result["report_id"], subject="owner-a", limit=1)
    assert page["records"][0]["content"] == body
    assert page["records"][0]["person_name"] == "测试联系人"
    assert page["records"][0]["direction"] == "inbound"
    assert page["next_offset"] == 1
    following = producer.read_page(result["report_id"], subject="owner-a", offset=1)
    assert following["records"][0]["direction"] == "outbound"
    assert following["next_offset"] is None


@pytest.mark.asyncio
async def test_empty_day_is_an_explicit_zero_report(tmp_path):
    _, _, _, sink, producer = setup(tmp_path)
    result = await producer.run_once(at("2026-10-05T23:00"))
    assert result["total_count"] == 0
    assert sink.events[0]["data"]["empty_day"] is True
    assert producer.read_page(result["report_id"], subject="owner-a")["records"] == []


@pytest.mark.asyncio
async def test_retry_preserves_snapshot_and_restart_does_not_repeat(tmp_path):
    repo, service, person, sink, producer = setup(tmp_path)
    add(service, person, "2026-10-05T12:00", "原始快照")
    sink.fail = True
    with pytest.raises(ConnectionError):
        await producer.run_once(at("2026-10-05T23:00"))
    add(service, person, "2026-10-05T22:00", "发布失败后晚到")
    restarted_sink = EventSink()
    restarted = ChatEventProducer(
        repo, restarted_sink, owner="owner-a", storage_path=str(tmp_path / "reports")
    )
    result = await restarted.run_once(at("2026-10-05T23:05"))
    page = restarted.read_page(result["report_id"], subject="owner-a")
    assert page["window_end"] == "2026-10-05T23:00:00+08:00"
    assert [r["content"] for r in page["records"]] == ["原始快照"]
    assert await restarted.run_once(at("2026-10-05T23:06")) is None
    assert len(restarted_sink.events) == 1
    later = await restarted.run_once(at("2026-10-06T23:00"))
    late_page = restarted.read_page(later["report_id"], subject="owner-a")
    assert late_page["daily_count"] == 0
    assert late_page["supplemental_count"] == 1
    assert late_page["records"][0]["content"] == "发布失败后晚到"


@pytest.mark.asyncio
async def test_next_day_includes_late_and_post_cutoff_messages_once(tmp_path):
    _, service, person, _, producer = setup(tmp_path)
    add(service, person, "2026-10-05T12:00", "第一日报")
    await producer.run_once(at("2026-10-05T23:00"))
    add(service, person, "2026-10-05T22:10", "晚到")
    add(service, person, "2026-10-05T23:40", "截止之后")
    add(service, person, "2026-10-06T09:00", "第二天")
    result = await producer.run_once(at("2026-10-06T23:00"))
    page = producer.read_page(result["report_id"], subject="owner-a")
    assert page["daily_count"] == 1
    assert page["supplemental_count"] == 2
    assert [r["content"] for r in page["records"]] == ["晚到", "截止之后", "第二天"]
    assert page["coverage"]["supplemental_days"] == ["2026-10-05"]
    third = await producer.run_once(at("2026-10-07T23:00"))
    assert producer.read_page(third["report_id"], subject="owner-a")["total_count"] == 0


@pytest.mark.asyncio
async def test_missing_original_is_explicit_and_later_content_is_supplemented(tmp_path):
    repo, service, person, _, producer = setup(tmp_path)
    row = add(service, person, "2026-10-05T10:00", "只有旧摘要", raw=False)
    first = await producer.run_once(at("2026-10-05T23:00"))
    page = producer.read_page(first["report_id"], subject="owner-a")
    assert page["content_unavailable_count"] == 1
    assert page["records"][0]["content"] is None
    assert "只有旧摘要" not in json.dumps(page, ensure_ascii=False)
    with repo.transaction() as session:
        item = session.get(Interaction, row.id)
        item.summary = "消息内容：后来补齐的原文"
    second = await producer.run_once(at("2026-10-06T23:00"))
    updated = producer.read_page(second["report_id"], subject="owner-a")
    assert updated["supplemental_count"] == 1
    assert updated["records"][0]["supplement_reason"] == "content_completed"
    assert updated["records"][0]["content"] == "后来补齐的原文"
    assert (
        producer.read_page(first["report_id"], subject="owner-a")["records"][0]["content"] is None
    )


@pytest.mark.asyncio
async def test_long_unicode_message_can_be_reconstructed_without_loss(tmp_path):
    _, service, person, _, producer = setup(tmp_path)
    body = "保留每一行🙂\n" * 3000 + "结束"
    add(service, person, "2026-10-05T10:00", body)
    result = await producer.run_once(at("2026-10-05T23:00"))
    record = producer.read_page(result["report_id"], subject="owner-a")["records"][0]
    pieces, offset = [record["content"]], record["next_content_offset"]
    while offset is not None:
        chunk = producer.read_message(
            result["report_id"], record["id"], subject="owner-a", offset=offset, limit=12000
        )
        pieces.append(chunk["content"])
        offset = chunk["next_offset"]
    assert "".join(pieces) == body
    assert record["content_total_chars"] == len(body)


@pytest.mark.asyncio
async def test_cross_subject_and_path_traversal_are_rejected(tmp_path):
    repo, _, _, _, producer = setup(tmp_path)
    result = await producer.run_once(at("2026-10-05T23:00"))
    with pytest.raises(PermissionError):
        producer.read_page(result["report_id"], subject="owner-b")
    with pytest.raises(ValueError):
        producer.read_page("../state", subject="owner-a")
    moved_owner = ChatEventProducer(
        repo, EventSink(), owner="owner-b", storage_path=str(tmp_path / "reports")
    )
    with pytest.raises(ValueError, match="identity"):
        await moved_owner.run_once(at("2026-10-06T23:00"))


@pytest.mark.asyncio
async def test_missed_schedule_keeps_original_day_and_reports_after_restart(tmp_path):
    _, service, person, _, producer = setup(tmp_path)
    add(service, person, "2026-10-05T12:00", "停机前消息")
    assert await producer.run_once(at("2026-10-05T20:00")) is None
    first = await producer.run_once(at("2026-10-07T08:00"))
    first_page = producer.read_page(first["report_id"], subject="owner-a")
    assert first_page["business_day"] == "2026-10-05"
    assert first_page["window_end"] == "2026-10-05T23:00:00+08:00"
    second = await producer.run_once(at("2026-10-07T08:01"))
    assert (
        producer.read_page(second["report_id"], subject="owner-a")["business_day"] == "2026-10-06"
    )
    assert await producer.run_once(at("2026-10-07T08:02")) is None


@pytest.mark.asyncio
async def test_mcp_read_tools_keep_owner_check_even_if_middleware_is_bypassed(tmp_path):
    _, service, person, sink, producer = setup(tmp_path)
    add(service, person, "2026-10-05T10:00", "仅限本人")
    result = await producer.run_once(at("2026-10-05T23:00"))
    server = create_mcp(service, Settings(mcp_development_no_auth=True), chat_reports=producer)
    names = {tool.name for tool in await server.list_tools()}
    assert {"get_chat_event_report", "get_chat_event_message"} <= names
    page = await server.call_tool(
        "get_chat_event_report", {"report_id": result["report_id"]}, run_middleware=False
    )
    assert page.structured_content["records"][0]["content"] == "仅限本人"
    sink.subject = "owner-b"
    with pytest.raises((ToolError, PermissionError), match="access denied"):
        await server.call_tool(
            "get_chat_event_report", {"report_id": result["report_id"]}, run_middleware=False
        )


def test_defaults_are_explicit_opt_in_and_taipei_2300():
    settings = Settings()
    assert settings.chat_events_enabled is False
    assert settings.chat_event_owner == ""
    assert settings.chat_event_timezone == "Asia/Taipei"
    assert settings.chat_event_time == "23:00"


@pytest.mark.asyncio
async def test_real_event_service_restricts_owner_and_recovers_delivery(tmp_path):
    import base64

    from mcp_platform import RuntimeConfig
    from mcp_platform.events import EventError, EventService, WebhookResponse

    class Callback:
        def __init__(self):
            self.posts = []

        async def post(self, url, body, headers):
            payload = json.loads(body)
            self.posts.append(payload)
            if payload.get("type") == "verification":
                return WebhookResponse(
                    200, json.dumps({"challenge": payload["challenge"]}).encode()
                )
            return WebhookResponse(202, b"{}")

    config = RuntimeConfig(
        name="crm-event-test",
        authorized_usernames={"owner-a", "owner-b"},
        public_base_url="https://crm.example.com",
        oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
        oidc_client_id="crm-test",
        oidc_client_secret="synthetic-client-secret",
        storage_path=str(tmp_path / "oauth"),
        storage_encryption_key="s" * 32,
        jwt_signing_key="j" * 32,
    )

    def clock():
        return at("2026-10-05T23:00").timestamp()

    callback = Callback()
    bus = EventService(
        config, storage_path=str(tmp_path / "delivery"), transport=callback, clock=clock
    )
    repo = CrmRepository("sqlite:///:memory:")
    service = CrmService(repo)
    person = service.create_person("集成测试联系人")
    add(service, person, "2026-10-05T10:00", "完整原文只留在受保护报告")
    producer = ChatEventProducer(
        repo, bus, owner="owner-a", storage_path=str(tmp_path / "snapshots")
    )
    subscription = {
        "name": EVENT_NAME,
        "arguments": {},
        "delivery": {
            "mode": "webhook",
            "url": "https://callback.example.com/events",
            "secret": "whsec_" + base64.b64encode(b"synthetic-webhook-test-secret-32").decode(),
        },
    }
    with pytest.raises(EventError, match="unavailable"):
        await bus.subscribe("owner-b", subscription)
    await bus.subscribe("owner-a", subscription)
    result = await producer.run_once(at("2026-10-05T23:00"))
    assert result["delivery"]["queued"] == 1
    assert (await bus.status())["pending"] == 1
    assert len(callback.posts) == 1
    reopened_bus = EventService(
        config, storage_path=str(tmp_path / "delivery"), transport=callback, clock=clock
    )
    reopened = ChatEventProducer(
        repo, reopened_bus, owner="owner-a", storage_path=str(tmp_path / "snapshots")
    )
    assert (await reopened_bus.run_delivery_once())["accepted"] == 1
    assert (await reopened_bus.status())["pending"] == 0
    assert await reopened.run_once(at("2026-10-05T23:01")) is None
    event = callback.posts[-1]
    assert event["name"] == EVENT_NAME
    assert "完整原文只留在受保护报告" not in json.dumps(event, ensure_ascii=False)
    page = reopened.read_page(result["report_id"], subject="owner-a")
    assert page["records"][0]["content"] == "完整原文只留在受保护报告"


def test_app_rejects_event_owner_outside_authorized_users_before_start(tmp_path):
    from personal_crm.app.server import create_app

    settings = Settings(
        chat_events_enabled=True,
        chat_event_owner="owner-b",
        oidc_authorized_usernames="owner-a",
        chat_event_storage_path=str(tmp_path / "events"),
    )
    with pytest.raises(ValueError, match="explicitly authorized"):
        create_app(settings, CrmRepository("sqlite:///:memory:"))


@pytest.mark.asyncio
async def test_unknown_client_watermark_never_creates_an_inverted_gap(tmp_path):
    from personal_crm.storage.models import SyncClient

    repo, _, _, _, producer = setup(tmp_path)
    with repo.transaction() as session:
        session.add(
            SyncClient(
                source="test",
                client_id="known",
                synced_through=at("2026-10-06T01:00"),
                last_seen_at=at("2026-10-05T23:00"),
            )
        )
        session.add(
            SyncClient(
                source="test",
                client_id="unknown",
                synced_through=None,
                last_seen_at=at("2026-10-05T23:00"),
            )
        )
    result = await producer.run_once(at("2026-10-05T23:00"))
    page = producer.read_page(result["report_id"], subject="owner-a")
    gap = page["coverage"]["pending_windows"][0]
    assert gap["start"] == "2026-10-05T00:00:00+08:00"
    assert datetime.fromisoformat(gap["start"]) < datetime.fromisoformat(gap["end"])
