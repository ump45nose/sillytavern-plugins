"""多客户端并发、跨设备去重和独立水位的契约测试。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.connector.chatlog import ChatlogMessageSource
from personal_crm.connector.config import ConnectorConfig
from personal_crm.storage import CrmRepository
from tests.test_webhook_app import _payload


def _device_payload(client_id, offset, server_id="server-1", account="same-account"):
    """模拟两台设备同账号消息，保留各设备不同的旧键。"""

    source = ChatlogMessageSource(ConnectorConfig(account_namespace=account))
    scope = {
        "account_id": client_id,
        "account_namespace": account,
        "conversation_id": "conversation",
        "person_name": "Alice",
        "requested_id": "Alice",
        "conversation_type": "direct",
    }
    event = source._event(
        {
            "ts": 1788483600,
            "server_id": server_id,
            "source_offset": offset,
            "content": "不外发正文",
        },
        scope,
    )
    from personal_crm.connector.sync import WeChatConnector

    payload = _payload()
    payload.update(source="chatlog", client_id=client_id, synced_through="2026-09-04T02:00:00Z")
    item = payload["interactions"][0]
    item["source_event_key"] = WeChatConnector._key(event)
    item["source_message_key"] = event["source_message_key"]
    payload["facts"][0]["source_event_key"] = item["source_event_key"]
    return payload


def _file_client(tmp_path):
    """使用真实文件型 SQLite 验证多个 HTTP 工作线程共享数据库。"""

    repo = CrmRepository(f"sqlite:///{tmp_path / 'multi.db'}")
    settings = Settings(mcp_development_no_auth=True, wechat_webhook_secret="secret", reminder_scheduler_enabled=False)
    return TestClient(create_app(settings, repo)), repo


def test_two_devices_deduplicate_same_server_message(tmp_path):
    """设备账号目录和 offset 不同仍只落一条互动，Fact 指向同一互动。"""

    client, repo = _file_client(tmp_path)
    first = _device_payload("mac-pro", "row-1")
    second = _device_payload("mac-air", "row-99")
    assert (
        first["interactions"][0]["source_event_key"]
        != second["interactions"][0]["source_event_key"]
    )
    assert (
        first["interactions"][0]["source_message_key"]
        == second["interactions"][0]["source_message_key"]
    )
    headers = {"X-Webhook-Token": "secret"}
    assert (
        client.post("/api/v1/webhooks/wechat", json=first, headers=headers).json()["accepted"] == 2
    )
    reply = client.post("/api/v1/webhooks/wechat", json=second, headers=headers)
    assert reply.status_code == 200 and reply.json()["duplicates"] == 2
    assert len(repo.search_people()) == len(repo.list_interactions()) == len(repo.list_facts()) == 1
    assert repo.list_facts()[0].source_interaction_id == repo.list_interactions()[0].id
    assert client.get("/api/v1/webhooks/wechat/clients").status_code == 401
    states = client.get("/api/v1/webhooks/wechat/clients", headers=headers).json()["clients"]
    assert {item["client_id"] for item in states} == {"mac-pro", "mac-air"}


def test_concurrent_clients_do_not_create_duplicate_people_or_facts(tmp_path):
    """并发 HTTP 批次在去重前取 SQLite 写锁，避免查后插入竞态。"""

    client, repo = _file_client(tmp_path)
    payloads = [_device_payload(f"mac-{index}", f"row-{index}") for index in range(4)]

    def send(payload):
        """从独立工作线程发送一个设备批次。"""
        return client.post(
            "/api/v1/webhooks/wechat", json=payload, headers={"X-Webhook-Token": "secret"}
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        replies = list(pool.map(send, payloads))
    assert all(reply.status_code == 200 for reply in replies)
    assert sum(reply.json()["accepted"] for reply in replies) == 2
    assert len(repo.search_people()) == len(repo.list_interactions()) == len(repo.list_facts()) == 1
    assert len(repo.list_sync_clients()) == 4


def test_old_event_key_is_enriched_without_reimport(tmp_path):
    """旧协议已落库消息能补齐稳定身份，然后由另一台设备幂等重放。"""

    client, repo = _file_client(tmp_path)
    headers = {"X-Webhook-Token": "secret"}
    modern = _device_payload("mac-pro", "row-1")
    legacy = deepcopy(modern)
    legacy.pop("client_id")
    legacy.pop("synced_through")
    legacy["interactions"][0].pop("source_message_key")
    assert client.post("/api/v1/webhooks/wechat", json=legacy, headers=headers).status_code == 200
    assert (
        client.post("/api/v1/webhooks/wechat", json=modern, headers=headers).json()["accepted"] == 0
    )
    other = _device_payload("mac-air", "row-999")
    assert (
        client.post("/api/v1/webhooks/wechat", json=other, headers=headers).json()["accepted"] == 0
    )
    assert len(repo.list_interactions()) == 1
    assert repo.list_interactions()[0].source_message_key


def test_account_namespace_and_server_message_id_isolate_events(tmp_path):
    """不同账号或同一秒内不同服务器消息不能被错误合并。"""

    client, repo = _file_client(tmp_path)
    for payload in (
        _device_payload("mac-pro", "row-1"),
        _device_payload("mac-air", "row-1", account="other-account"),
        _device_payload("mac-air", "row-2", server_id="server-2"),
    ):
        assert (
            client.post(
                "/api/v1/webhooks/wechat", json=payload, headers={"X-Webhook-Token": "secret"}
            ).status_code
            == 200
        )
    assert len(repo.list_interactions()) == 3


def test_client_watermarks_are_independent_and_do_not_regress(tmp_path):
    """空窗口独立推进设备水位，重试旧窗口不倒退，错误批次不注册客户端。"""

    client, repo = _file_client(tmp_path)
    payload = _device_payload("mac-pro", "row-1")
    payload.update(interactions=[], facts=[])
    headers = {"X-Webhook-Token": "secret"}
    for client_id, until in (
        ("mac-pro", "2026-09-10T00:00:00Z"),
        ("mac-air", "2026-09-05T00:00:00Z"),
        ("mac-pro", "2026-09-01T00:00:00Z"),
    ):
        payload.update(client_id=client_id, synced_through=until)
        assert (
            client.post("/api/v1/webhooks/wechat", json=payload, headers=headers).status_code == 200
        )
    states = {item["client_id"]: item for item in repo.list_sync_clients()}
    assert states["mac-pro"]["synced_through"] == datetime(2026, 9, 10, tzinfo=UTC).isoformat()
    assert states["mac-air"]["synced_through"] == datetime(2026, 9, 5, tzinfo=UTC).isoformat()
    invalid = _device_payload("invalid-client", "row-1")
    invalid["facts"][0]["fact_type"] = "invalid"
    assert client.post("/api/v1/webhooks/wechat", json=invalid, headers=headers).status_code == 422
    assert len(repo.list_sync_clients()) == 2


def test_missing_server_id_does_not_guess_cross_device_identity():
    """缺少服务器消息 ID 时保留设备去重，不能按秒或正文猜测跨机身份。"""

    source = ChatlogMessageSource(ConnectorConfig())
    scope = {
        "account_id": "account",
        "conversation_id": "conversation",
        "person_name": "Alice",
        "requested_id": "Alice",
        "conversation_type": "direct",
    }
    assert source._event({"ts": 1788483600, "server_id": "0", "content": ""}, scope)["source_message_key"] is None


def test_deployed_content_enrichment_and_daily_queries_are_preserved(tmp_path):
    """升级保留线上长内容接收、旧记录补齐及分页查询功能。"""

    client, repo = _file_client(tmp_path)
    payload = _device_payload("mac-pro", "row-1")
    headers = {"X-Webhook-Token": "secret"}
    assert client.post("/api/v1/webhooks/wechat", json=payload, headers=headers).status_code == 200
    content = "仅用于测试的内容" * 200
    payload["interactions"][0]["summary"] = "消息内容：" + content
    response = client.post("/api/v1/webhooks/wechat", json=payload, headers=headers)
    assert response.status_code == 200 and response.json()["accepted"] == 0
    start, end = datetime(2026, 9, 4, tzinfo=UTC), datetime(2026, 9, 5, tzinfo=UTC)
    assert repo.daily_chat_records(start, end)[0]["content"] == content
    assert repo.daily_summary(start, end)["content_summaries"]["Alice"] == [content]


def test_older_client_fact_does_not_supersede_newer_fact(tmp_path):
    """客户端窗口乱序时，旧事实保存为历史而不会覆盖较新的当前状态。"""

    client, repo = _file_client(tmp_path)
    newer = _device_payload("mac-pro", "row-1", server_id="new")
    newer["facts"][0].update(content="较新的事实", observed_at="2026-09-10T00:00:00Z")
    older = _device_payload("mac-air", "row-2", server_id="old")
    older["facts"][0].update(content="较旧的事实", observed_at="2026-09-01T00:00:00Z")
    for payload in (newer, older):
        assert (
            client.post(
                "/api/v1/webhooks/wechat", json=payload, headers={"X-Webhook-Token": "secret"}
            ).status_code
            == 200
        )
    facts = {fact.content: fact.status for fact in repo.list_facts()}
    assert facts == {"较新的事实": "active", "较旧的事实": "superseded"}
