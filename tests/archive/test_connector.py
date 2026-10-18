import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx

from personal_crm.connector.chatlog import ChatlogMessageSource, SourceBatch
from personal_crm.connector.checkpoint import load, save
from personal_crm.connector.config import ConnectorConfig
from personal_crm.connector.sync import WeChatConnector


def source_event(index=0, content="原文", typ=1):
    scope = dict(
        account_id="local-account",
        account_namespace="me",
        conversation_id="you",
        conversation_type="direct",
        person_name="小王",
        requested_id="you",
    )
    return ChatlogMessageSource(ConnectorConfig())._event(
        dict(
            ts=1788483600 + index,
            content=content,
            msg_type=typ,
            is_self=False,
            server_id=str(index + 1),
            source_offset=str(index),
        ),
        scope,
    )


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.response = httpx.Response(
            status,
            json=body or {"accepted": 1, "duplicates": 0, "missing_media_keys": []},
            request=httpx.Request("POST", "http://nas"),
        )

    def raise_for_status(self):
        self.response.raise_for_status()

    def json(self):
        return {"missing_media_keys": [], **self.response.json()}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posted = []

    def post(self, url, **kw):
        self.posted.append((url, kw["json"]))
        return self.responses.pop(0)


def test_only_direct_source_and_first_activation_boundary(tmp_path, monkeypatch):
    cfg = ConnectorConfig(
        chatlog_executable=__file__, chatlog_scopes_path=str(tmp_path / "missing")
    )
    conversations = [
        dict(account_id="a", conversation_id="peer", label="备注"),
        dict(account_id="a", conversation_id="g@chatroom", label="群"),
        dict(account_id="a", conversation_id="empty", label="空联系人", message_count=0),
    ]
    monkeypatch.setattr(
        "personal_crm.connector.chatlog.subprocess.run",
        lambda *a, **k: SimpleNamespace(
            returncode=0, stdout=json.dumps({"available": True, "conversations": conversations})
        ),
    )
    source = ChatlogMessageSource(cfg)
    scopes = source._scopes()
    assert len(scopes) == 1 and scopes[0]["person_name"] == "备注"
    start, end = source._window({})
    assert (datetime.now(UTC) - start).total_seconds() < 2
    old = datetime(2026, 10, 14, tzinfo=UTC)
    assert source._window({"last_synced_at": old.isoformat()})[0] <= old


def test_ingest_parts_and_failure_watermark(tmp_path):
    cfg = ConnectorConfig(
        webhook_url="http://nas/api/v1/crm/ingest/wechat", checkpoint_path=str(tmp_path / "cp")
    )
    initial = {"last_synced_at": "2026-09-01T00:00:00+00:00"}
    save(cfg.checkpoint_path, initial)
    batch = SourceBatch([source_event(i) for i in range(1001)], datetime(2026, 9, 5, tzinfo=UTC))
    source = SimpleNamespace(read=lambda _: batch)
    bad = FakeClient([FakeResponse(body={"accepted": 500, "duplicates": 0}), FakeResponse(503)])
    assert WeChatConnector(cfg, bad, source).sync_once().errors
    assert load(cfg.checkpoint_path) == initial
    assert bad.posted[0][1]["synced_through"] is None
    good = FakeClient(
        [
            FakeResponse(body={"accepted": 0, "duplicates": 500}),
            FakeResponse(body={"accepted": 500, "duplicates": 0}),
            FakeResponse(),
        ]
    )
    result = WeChatConnector(cfg, good, source).sync_once()
    assert result.sent and result.accepted == 501 and result.duplicates == 500
    assert load(cfg.checkpoint_path) == {"last_synced_at": batch.until.isoformat()}
    assert set(good.posted[0][1]["messages"][0]) == {
        "key",
        "account",
        "peer",
        "name",
        "sent_at",
        "sender",
        "is_self",
        "content",
        "attachment",
    }


def test_first_failure_preserves_activation_and_safe_output(tmp_path):
    cfg = ConnectorConfig(checkpoint_path=str(tmp_path / "cp"))

    def fail(_):
        raise OSError("private chat content")

    connector = WeChatConnector(cfg, source=SimpleNamespace(read=fail))
    first = connector.sync_once()
    state = load(cfg.checkpoint_path)
    assert first.errors == ["chatlog: OSError"]
    connector.sync_once()
    assert load(cfg.checkpoint_path) == state
