"""全会话、分批失败恢复及源消息无损归档的契约。"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.connector.chatlog import ChatlogMessageSource, ChatlogSourceError, SourceBatch
from personal_crm.connector.checkpoint import load, save
from personal_crm.connector.config import ConnectorConfig
from personal_crm.connector.sync import WeChatConnector
from personal_crm.storage import CrmRepository
from personal_crm.webhook.handler import WebhookInteraction
from tests.test_connector import FakeClient, FakeResponse


def scope(index=0, kind="direct"):
    return {"requested_id": str(index), "person_name": "同名会话", "account_id": "local-account",
            "account_namespace": "main", "conversation_id": str(index) + ("@chatroom" if kind == "group" else ""), "conversation_type": kind}


def source_event(content=" \n原文\t ", index=0, offset="row-1"):
    return ChatlogMessageSource(ConnectorConfig())._event(
        {"ts": 1788483600, "content": content, "msg_type": 49, "is_self": False,
         "server_id": str(index + 1), "source_offset": offset, "sender": "sender-id",
         "extra": {"xml": "<msg/>", "unknown_field": [1, 2]}}, scope(index))


@pytest.mark.parametrize("mode,groups", [("all", 1), ("all_direct", 0)])
def test_directory_chunks_keep_source_fields_and_fail_closed(tmp_path, monkeypatch, mode, groups):
    pinned = tmp_path / "scopes.json"
    pinned.write_text(json.dumps([scope()]))
    cfg = ConnectorConfig(chatlog_executable=__file__, chatlog_scopes_path=str(pinned),
                          chatlog_scope_mode=mode, allowed_contacts={"old-allowlist"})
    requested = []
    fail = False

    def run(args, **kwargs):
        if args[1] == "directory":
            directory = {"available": True, "conversations": [scope(i) for i in range(129)] + [scope(129, "group"), dict(scope(130), conversation_type="group")]}
            return SimpleNamespace(returncode=0, stdout=json.dumps(directory))
        request = json.loads(kwargs["input"])
        requested.append(request)
        frames = [{"frame": "record", "scope_index": 0, "record": source_event()["message"]["record"]}]
        if not (fail and len(requested) == 2):
            frames.append({"frame": "complete"})
        return SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, frames)))

    monkeypatch.setattr("personal_crm.connector.chatlog.subprocess.run", run)
    source = ChatlogMessageSource(cfg)
    corrected = next(x for x in source._scopes() if x["conversation_id"] == "130")
    assert corrected["conversation_type"] == "direct" and corrected["directory_conversation_type"] == "group"
    batch = source.read({})
    assert [len(x["scopes"]) for x in requested] == [128, 2 + groups]
    assert sum(s["conversation_type"] == "group" for x in requested for s in x["scopes"]) == groups
    assert batch.events[0]["content"] == " \n原文\t "
    assert batch.events[0]["message"]["record"]["extra"]["unknown_field"] == [1, 2]
    assert batch.events[0]["facts"] == []
    fail = True
    requested.clear()
    with pytest.raises(ChatlogSourceError, match="incomplete_stream"):
        ChatlogMessageSource(cfg).read({})


def test_webhook_chunks_only_commit_watermark_after_last_part(tmp_path):
    end = datetime(2026, 9, 5, tzinfo=UTC)
    events = [source_event(index=i) for i in range(1001)]
    source = SimpleNamespace(read=lambda state: SourceBatch(events, end))
    cfg = ConnectorConfig(webhook_url="http://nas/hook", checkpoint_path=str(tmp_path / "checkpoint"),
                          allowed_contacts={"old-allowlist"})
    save(cfg.checkpoint_path, {"keys": ["old-key"], "last_synced_at": "2026-09-03T00:00:00Z"})
    before = load(cfg.checkpoint_path)
    failed = FakeClient([], [FakeResponse(200, {"accepted": 500}), FakeResponse(503)])
    result = WeChatConnector(cfg, failed, source).sync_once()
    assert result.errors and load(cfg.checkpoint_path) == before
    assert all(p[1]["synced_through"] is None for p in failed.posted)
    good = FakeClient([], [FakeResponse(200, {"duplicates": 500}), FakeResponse(200, {"accepted": 500}), FakeResponse(200, {"accepted": 1})])
    result = WeChatConnector(cfg, good, source).sync_once()
    assert result.sent and (result.accepted, result.duplicates) == (501, 500)
    assert [len(p[1]["interactions"]) for p in good.posted] == [500, 500, 1]
    assert good.posted[0][1]["batch_id"] == failed.posted[0][1]["batch_id"]
    assert [p[1]["synced_through"] for p in good.posted] == [None, None, end.isoformat()]
    assert good.posted[0][1]["interactions"][0]["summary"] == "消息内容： \n原文\t "
    assert load(cfg.checkpoint_path)["last_synced_at"] == end.isoformat()


def test_original_message_roundtrip_enriches_without_new_interaction(tmp_path):
    from personal_data_hub.storage import Store
    store = Store(f"sqlite:///{tmp_path / 'hub.db'}", tmp_path / "assets")
    store.register("crm", "owner", "crm_pg", "authoritative_inventory")
    repo = CrmRepository(str(store.engine.url), hub_store=store)
    client = TestClient(create_app(Settings(mcp_development_no_auth=True, wechat_webhook_secret="secret", reminder_scheduler_enabled=False), repo))
    cfg = ConnectorConfig(checkpoint_path=str(tmp_path / "cp"))
    connector = WeChatConnector(cfg, client=FakeClient([]), source=SimpleNamespace(read=lambda state: SourceBatch([source_event()], datetime(2026, 9, 5, tzinfo=UTC))))
    result = connector.sync_once(dry_run=True)
    item = result.interactions[0]
    payload = {"batch_id": result.batch_id, "source": "chatlog", "interactions": [dict(item, summary="旧互动摘要")], "facts": []}
    payload["interactions"][0].pop("message")
    headers = {"X-Webhook-Token": "secret"}
    assert client.post("/api/v1/webhooks/wechat", json=payload, headers=headers).status_code == 200
    original_id = repo.list_interactions()[0].id
    content = " \n" + "长正文" * 30000 + "\x00\t "
    message = source_event(content=content)["message"]
    payload["interactions"][0] = dict(item, message=message, summary="消息内容：" + content)
    assert client.post("/api/v1/webhooks/wechat", json=payload, headers=headers).json()["duplicates"] == 1
    stored = repo.list_interactions()
    assert len(stored) == 1 and stored[0].id == original_id and stored[0].message == message
    archive = store.get_record(store.identity("crm", "interactions:" + original_id))
    assert archive["raw"]["message"] == message
    daily = repo.daily_chat_records(datetime(2026, 9, 4, tzinfo=UTC), datetime(2026, 9, 5, tzinfo=UTC))[0]
    assert daily["content"] == content and daily["message_type"] == 49
    # 另一设备的 offset 不覆盖已归档源消息，也不会新增互动。
    other = source_event(content=content, offset="row-other")
    payload["interactions"][0].update(source_event_key=WeChatConnector._key(other), message=other["message"])
    assert client.post("/api/v1/webhooks/wechat", json=payload, headers=headers).json()["duplicates"] == 1
    assert repo.list_interactions()[0].message == message
    # 显式删除后回放不能复活记录。
    from personal_data_hub.contracts import Batch
    store.ingest("crm", Batch(deletions=["interactions:" + original_id]))
    assert client.post("/api/v1/webhooks/wechat", json=payload, headers=headers).status_code == 200
    assert repo.list_interactions() == []


def test_invalid_source_message_and_archive_failure_roll_back(tmp_path, monkeypatch):
    from personal_data_hub.storage import Store
    store = Store(f"sqlite:///{tmp_path / 'hub.db'}", tmp_path / "assets")
    store.register("crm", "owner", "crm_pg", "authoritative_inventory")
    repo = CrmRepository(str(store.engine.url), hub_store=store)
    cfg = ConnectorConfig(checkpoint_path=str(tmp_path / "cp"))
    source = SimpleNamespace(read=lambda state: SourceBatch([source_event()], datetime(2026, 9, 5, tzinfo=UTC)))
    item = WebhookInteraction.model_validate(WeChatConnector(cfg, client=FakeClient([]), source=source).sync_once(dry_run=True).interactions[0]).model_dump()
    item["message"]["record"]["ts"] += 1
    with pytest.raises(ValueError, match="time mismatch"):
        repo.import_wechat_batch("chatlog", [item], [])
    item["message"]["record"]["ts"] -= 1
    monkeypatch.setattr(store, "ingest", lambda *a, **kw: (_ for _ in ()).throw(ValueError("archive failed")))
    with pytest.raises(ValueError, match="archive failed"):
        repo.import_wechat_batch("chatlog", [item], [])
    assert repo.list_interactions() == [] and repo.search_people() == []


def test_same_display_name_does_not_merge_conversations():
    repo = CrmRepository("sqlite:///:memory:")
    for i in range(2):
        e = source_event(index=i)
        cfg = ConnectorConfig()
        source = SimpleNamespace(read=lambda state, e=e: SourceBatch([e], datetime(2026, 9, 5, tzinfo=UTC)))
        item = WebhookInteraction.model_validate(WeChatConnector(cfg, client=FakeClient([]), source=source).sync_once(dry_run=True).interactions[0]).model_dump()
        repo.import_wechat_batch("chatlog", [item], [])
    assert len(repo.search_people()) == 2
