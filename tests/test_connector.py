"""Mac Connector 的隐私、过滤、失败恢复与 checkpoint 契约测试。"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from personal_crm.connector.checkpoint import load, save
from personal_crm.connector.config import ConnectorConfig
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
        webhook_url="http://nas/hook", checkpoint_path=str(tmp_path / "cp.json"), **kwargs
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


def test_welink_read_failure_does_not_raise_or_advance(tmp_path):
    """验证读取 WeLink 失败时返回可观察错误，不推进 checkpoint。"""

    class OfflineClient(FakeClient):
        def get(self, url):
            raise httpx.ConnectError("offline")

    config = ConnectorConfig(checkpoint_path=str(tmp_path / "cp.json"))
    result = WeChatConnector(config, OfflineClient([])).sync_once()
    assert not result.sent and result.errors == ["welink: ConnectError"]
    assert not Path(config.checkpoint_path).exists()
