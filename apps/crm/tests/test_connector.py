"""Mac Connector 的隐私、过滤、失败恢复与 checkpoint 契约测试。"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from personal_crm.connector.chatlog import ChatlogMessageSource, ChatlogSourceError
from personal_crm.connector.checkpoint import load, save
from personal_crm.connector.cli import _output
from personal_crm.connector.config import ConnectorConfig
from personal_crm.connector.fact_extractor import RuleBasedFactExtractor
from personal_crm.connector.sync import WeChatConnector


class FakeResponse:
    """最小化 HTTP 响应替身，避免测试依赖真实 WeLink 或 NAS。"""

    def __init__(self, status_code=200, body=None, error=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.content = json.dumps(self._body).encode() if body is not None else b""
        self.error = error

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.error:
            raise self.error
        if not 200 <= self.status_code < 300:
            raise httpx.HTTPStatusError(
                "upstream error",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(self.status_code),
            )


class FakeClient:
    """记录请求并按队列返回响应，覆盖断网、5xx 和成功场景。"""

    def __init__(self, events, posts=None):
        self.events = events
        self.posts = list(posts or [FakeResponse(200, {})])
        self.posted = []

    def get(self, url):
        return FakeResponse(200, self.events)

    def post(self, url, json, headers):
        self.posted.append((url, json, headers))
        result = self.posts.pop(0)
        if result.error:
            raise result.error
        return result


def event(contact="Alice", timestamp="2026-09-04T01:00:00+00:00", text="secret"):
    """构造带稳定业务 id 的适配器消息样本。"""
    return {"id": "evt-1", "contact": contact, "timestamp": timestamp, "text": text}


def make_connector(tmp_path, events, posts=None, **kwargs):
    """使用临时 checkpoint 创建连接器，确保测试不污染用户目录。"""
    config = ConnectorConfig(
        source_type="welink",
        webhook_url="http://nas/hook",
        checkpoint_path=str(tmp_path / "cp.json"),
        **kwargs,
    )
    return WeChatConnector(config, FakeClient(events, posts)), config


def test_welink_response_wrappers_and_privacy_payload(tmp_path):
    """验证 data 外壳可读，且出站 payload 不含 raw/text/content 原文。"""
    connector, _ = make_connector(tmp_path, event())
    connector.client.events = {"data": [event()]}
    result = connector.sync_once()
    assert result.sent
    payload = connector.client.posted[0][1]
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "secret" not in serialized
    assert all(
        not any(k in item for k in ("raw", "text", "content")) for item in payload["interactions"]
    )
    assert payload["interactions"][0]["person_name"] == "Alice"


def test_allowlist_and_time_window(tmp_path):
    """验证联系人白名单、since 和 until 会共同排除范围外事件。"""
    connector, _ = make_connector(
        tmp_path,
        [
            event("Alice", "2026-09-03T23:59:00+00:00"),
            event("Alice"),
            event("Bob", "2026-09-04T02:01:00+00:00"),
        ],
        allowed_contacts={"Alice"},
        since=datetime(2026, 9, 4, 0, tzinfo=UTC),
        until=datetime(2026, 9, 4, 2, tzinfo=UTC),
    )
    result = connector.sync_once(dry_run=True)
    assert len(result.interactions) == 1
    assert result.interactions[0]["person_name"] == "Alice"


def test_key_is_stable_across_order_and_payload_has_no_source_text(tmp_path):
    """验证 source_event_key 由业务字段决定，不随批次顺序改变。"""
    first, _ = make_connector(tmp_path, [event()])
    second, _ = make_connector(tmp_path, [dict(event(), extra="different")])
    assert first._key(event()) == second._key(dict(event(), extra="different"))


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(503, {}),
        FakeResponse(200, {"errors": ["bad"]}),
        FakeResponse(error=httpx.ConnectError("offline")),
    ],
)
def test_failure_does_not_advance_checkpoint(tmp_path, response):
    """验证断网、5xx 和业务 errors 都不推进 checkpoint。"""
    connector, config = make_connector(tmp_path, [event()], [response])
    result = connector.sync_once()
    assert not result.sent and result.errors
    assert not Path(config.checkpoint_path).exists()


def test_success_advances_and_same_batch_retry_is_idempotent(tmp_path):
    """验证成功写入 checkpoint，随后相同批次重试不重复发送。"""
    connector, config = make_connector(
        tmp_path, [event()], [FakeResponse(200, {}), FakeResponse(200, {})]
    )
    first = connector.sync_once()
    assert first.sent and uuid.UUID(first.batch_id)
    state = load(config.checkpoint_path)
    assert state["keys"] and state["last_batch_id"]
    assert state["last_synced_at"]
    assert connector.sync_once().interactions == []
    assert len(connector.client.posted) == 1


def test_connector_loads_explicit_launchd_env_file(tmp_path, monkeypatch):
    """验证 launchd 指定的独立环境文件可被连接器读取。"""

    env_file = tmp_path / "connector.env"
    env_file.write_text(
        "CRM_WEBHOOK_URL=https://crm.example.com/api/v1/webhooks/wechat\n"
        "WECHAT_CONTACTS=Alice,Bob\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CRM_ENV_FILE", str(env_file))
    monkeypatch.delenv("CRM_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("WECHAT_CONTACTS", raising=False)
    config = ConnectorConfig.from_env()
    assert config.webhook_url.endswith("/api/v1/webhooks/wechat")
    assert config.allowed_contacts == {"Alice", "Bob"}


def test_checkpoint_save_is_atomic(tmp_path, monkeypatch):
    """验证 checkpoint 使用同目录临时文件并通过 replace 原子替换。"""
    target = tmp_path / "checkpoint.json"
    calls = []
    real_replace = __import__("os").replace
    monkeypatch.setattr(
        "personal_crm.connector.checkpoint.os.replace",
        lambda src, dst: (calls.append((src, dst)), real_replace(src, dst))[1],
    )
    save(str(target), {"keys": ["x"]})
    assert load(str(target)) == {"keys": ["x"]}
    assert calls and Path(calls[0][0]).parent == target.parent


def test_upgrade_enriches_known_event_once_and_preserves_checkpoint_keys(tmp_path):
    """已确认旧事件首次补齐跨机身份；随后两个去重集合同时生效。"""

    message = dict(event(), source_message_key="a" * 64)
    connector, config = make_connector(tmp_path, [message], client_id="mac-pro")
    legacy_key = connector._key(message)
    save(config.checkpoint_path, {"keys": [legacy_key, "older-key"]})
    result = connector.sync_once()
    assert result.sent and len(result.interactions) == 1
    payload = connector.client.posted[0][1]
    assert payload["client_id"] == "mac-pro" and payload["synced_through"]
    state = load(config.checkpoint_path)
    assert set(state["keys"]) == {legacy_key, "older-key"}
    assert state["message_keys"] == ["a" * 64]
    assert connector.sync_once().interactions == []


def test_welink_read_failure_does_not_raise_or_advance(tmp_path):
    """验证读取 WeLink 失败时返回可观察错误，不推进 checkpoint。"""

    class OfflineClient(FakeClient):
        def get(self, url):
            raise httpx.ConnectError("offline")

    config = ConnectorConfig(source_type="welink", checkpoint_path=str(tmp_path / "cp.json"))
    result = WeChatConnector(config, OfflineClient([])).sync_once()
    assert not result.sent and result.errors == ["welink: ConnectError"]
    assert not Path(config.checkpoint_path).exists()


def chatlog_config(tmp_path, scopes_path, **kwargs):
    """构造 chatlog 测试配置，二进制调用由 monkeypatch 接管。"""

    return ConnectorConfig(
        source_type="chatlog",
        chatlog_executable=__file__,
        chatlog_scope_mode="configured",
        chatlog_scopes_path=str(scopes_path),
        allowed_contacts={"Alice"},
        since=datetime(2026, 9, 4, tzinfo=UTC),
        checkpoint_path=str(tmp_path / "cp.json"),
        **kwargs,
    )


def test_chatlog_stream_maps_scope_and_preserves_raw_content(tmp_path, monkeypatch):
    """验证 NDJSON 记录按 scope 对齐，且完整源消息保留。"""

    scopes = tmp_path / "scopes.json"
    scopes.write_text(
        json.dumps(
            [
                {
                    "requested_id": "Alice",
                    "person_name": "Alice",
                    "account_id": "account",
                    "conversation_id": "conversation",
                    "conversation_type": "direct",
                }
            ]
        ),
        encoding="utf-8",
    )
    stdout = "\n".join(
        json.dumps(frame)
        for frame in (
            {"protocol": "message-stream-v1", "version": 1, "frame": "ready"},
            {
                "protocol": "message-stream-v1",
                "version": 1,
                "frame": "record",
                "scope_index": 0,
                "record": {
                    "ts": 1_788_480_000,
                    "content": "secret",
                    "msg_type": 1,
                    "is_self": True,
                    "server_id": "server-1",
                    "source_offset": "offset-1",
                },
            },
            {"protocol": "message-stream-v1", "version": 1, "frame": "complete"},
        )
    )
    monkeypatch.setattr(
        "personal_crm.connector.chatlog.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout, stderr="", returncode=0),
    )

    batch = ChatlogMessageSource(chatlog_config(tmp_path, scopes)).read({})
    assert len(batch.events) == 1
    assert batch.events[0]["contact"] == "Alice"
    assert batch.events[0]["direction"] == "outbound"
    assert batch.events[0]["content"] == "secret"
    assert batch.events[0]["message"]["record"]["content"] == "secret"


def test_rule_based_fact_extractor_only_accepts_explicit_inbound_statements():
    """验证高置信自述可抽取，自己发送、卡片和普通闲聊不会生成 Fact。"""

    extractor = RuleBasedFactExtractor()
    assert extractor.extract("我喜欢手冲咖啡。", "inbound") == [
        {"fact_type": "preference", "content": "喜欢手冲咖啡", "confidence": 0.92}
    ]
    assert extractor.extract("我准备换工作", "inbound") == [
        {"fact_type": "life_event", "content": "换工作", "confidence": 0.9}
    ]
    assert extractor.extract("我喜欢手冲咖啡。", "outbound") == []
    assert extractor.extract("<msg>我喜欢手冲咖啡</msg>", "inbound") == []


def test_chatlog_explicit_legacy_extraction_also_preserves_source(tmp_path, monkeypatch):
    """显式兼容事实抽取不影响忠实保存消息。"""

    scopes = tmp_path / "scopes.json"
    scopes.write_text(
        json.dumps(
            [
                {
                    "requested_id": "Alice",
                    "person_name": "Alice",
                    "account_id": "account",
                    "conversation_id": "conversation",
                    "conversation_type": "direct",
                }
            ]
        ),
        encoding="utf-8",
    )
    original = "我喜欢手冲咖啡。这句尾巴不应整体外发"
    stdout = "\n".join(
        json.dumps(frame)
        for frame in (
            {"protocol": "message-stream-v1", "version": 1, "frame": "ready"},
            {
                "protocol": "message-stream-v1",
                "version": 1,
                "frame": "record",
                "scope_index": 0,
                "record": {
                    "ts": 1_788_480_000,
                    "content": original,
                    "msg_type": 1,
                    "is_self": False,
                    "server_id": "server-2",
                    "source_offset": "offset-2",
                },
            },
            {"protocol": "message-stream-v1", "version": 1, "frame": "complete"},
        )
    )
    monkeypatch.setattr(
        "personal_crm.connector.chatlog.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=stdout, stderr="", returncode=0),
    )
    config = chatlog_config(tmp_path, scopes)
    config.fact_extraction_enabled = True

    event_payload = ChatlogMessageSource(config).read({}).events[0]
    assert [item["fact_type"] for item in event_payload["facts"]] == [
        "preference",
        "contact",
    ]
    assert event_payload["facts"][1]["content"] == "微信联系人：Alice"
    assert event_payload["content"] == original
    assert event_payload["message"]["record"]["content"] == original


def test_chatlog_incomplete_stream_fails_closed(tmp_path, monkeypatch):
    """验证缺少 complete 帧时整批失败，禁止推进任何同步水位。"""

    scopes = tmp_path / "scopes.json"
    scopes.write_text(
        json.dumps(
            [
                {
                    "requested_id": "Alice",
                    "account_id": "account",
                    "conversation_id": "conversation",
                    "conversation_type": "direct",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "personal_crm.connector.chatlog.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="", stderr="", returncode=0),
    )

    with pytest.raises(ChatlogSourceError, match="incomplete_stream"):
        ChatlogMessageSource(chatlog_config(tmp_path, scopes)).read({})


def test_watch_output_only_contains_batch_aggregates(tmp_path):
    """验证常驻日志不落人物名、互动摘要或其他逐条数据。"""

    connector, _ = make_connector(tmp_path, [event()])
    result = connector.sync_once(dry_run=True)
    output = _output(result, compact=True)
    assert output["interaction_count"] == 1
    assert "interactions" not in output
    assert "Alice" not in json.dumps(output)
