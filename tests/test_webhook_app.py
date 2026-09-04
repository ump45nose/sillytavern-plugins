"""Webhook 原子性、鉴权与健康检查测试。"""

import uuid

from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.storage import CrmRepository


def _client():
    """创建禁用 OAuth、启用 Webhook 的测试应用。"""

    repository = CrmRepository("sqlite:///:memory:")
    settings = Settings(wechat_webhook_secret="secret")
    return TestClient(create_app(settings, repository)), repository


def _payload():
    """构造不含微信原文的同步批次。"""

    return {
        "batch_id": "019933f0-0c00-7000-8000-000000000001",
        "source": "welink",
        "interactions": [
            {
                "person_name": "Alice",
                "wxid": "wxid_alice",
                "occurred_at": "2026-09-04T01:00:00Z",
                "interaction_type": "message",
                "channel": "wechat",
                "direction": "mutual",
                "summary": "讨论了近况",
                "source_reference": "welink:1",
                "source_event_key": "event-1",
            }
        ],
        "facts": [
            {
                "person_name": "Alice",
                "wxid": "wxid_alice",
                "fact_type": "life_event",
                "content": "最近搬家",
                "observed_at": "2026-09-04T01:00:00Z",
                "source_event_key": "event-1",
            }
        ],
    }


def test_health_and_webhook_authentication():
    """验证健康检查与共享密钥。"""

    client, _ = _client()
    assert client.get("/healthz").json() == {"status": "ok", "database": "ok"}
    assert client.post("/api/v1/webhooks/wechat", json=_payload()).status_code == 401


def test_webhook_is_idempotent_and_rejects_raw_text():
    """验证整批幂等，且额外 raw/text 字段被协议拒绝。"""

    client, repository = _client()
    headers = {"X-Webhook-Token": "secret"}
    first = client.post("/api/v1/webhooks/wechat", json=_payload(), headers=headers)
    second = client.post("/api/v1/webhooks/wechat", json=_payload(), headers=headers)
    assert first.json()["accepted"] == 2
    assert second.json()["duplicates"] == 2
    assert len(repository.list_interactions()) == 1
    unsafe = _payload()
    unsafe["interactions"][0]["text"] = "完整微信正文"
    assert client.post("/api/v1/webhooks/wechat", json=unsafe, headers=headers).status_code == 422


def test_webhook_batch_rolls_back_on_invalid_fact():
    """验证任一事实不合法时，前面的互动也不会落库。"""

    client, repository = _client()
    payload = _payload()
    payload["facts"][0]["fact_type"] = "unsupported"
    response = client.post(
        "/api/v1/webhooks/wechat",
        json=payload,
        headers={"X-Webhook-Token": "secret"},
    )
    assert response.status_code == 422
    assert repository.list_interactions() == []


def test_webhook_requires_uuid_batch_id():
    """验证批次 ID 使用标准 UUID，便于跨进程追踪和重试。"""

    client, _ = _client()
    payload = _payload()
    payload["batch_id"] = "not-a-uuid"
    response = client.post(
        "/api/v1/webhooks/wechat",
        json=payload,
        headers={"X-Webhook-Token": "secret"},
    )
    assert response.status_code == 422
    assert uuid.UUID(_payload()["batch_id"])
