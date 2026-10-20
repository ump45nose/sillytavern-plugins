"""微信正文归档后媒体回填的 HTTP 与 Hub 契约。"""

import hashlib
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.connector.config import ConnectorConfig
from personal_crm.connector.sync import WeChatConnector
from personal_crm.storage import CrmRepository
from personal_crm.webhook.handler import WebhookInteraction
from personal_data_hub.contracts import Batch, Record
from personal_data_hub.storage import Store
from tests.test_faithful_wechat import source_event
from tests.test_connector import FakeClient


def _fixture(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'hub.db'}", tmp_path / "assets")
    store.register("crm", "owner", "crm_pg", "authoritative_inventory")
    repo = CrmRepository(str(store.engine.url), hub_store=store)
    settings = Settings(mcp_development_no_auth=True, wechat_webhook_secret="secret",
                        reminder_scheduler_enabled=False)
    client = TestClient(create_app(settings, repo))
    event = source_event(content="原文\x00\t 保持完整")
    # Use the public dry-run conversion, while retaining the exact source message.
    from types import SimpleNamespace
    from personal_crm.connector.chatlog import SourceBatch
    connector = WeChatConnector(ConnectorConfig(), FakeClient([]),
                                SimpleNamespace(read=lambda state: SourceBatch([event], datetime(2026, 9, 5, tzinfo=UTC))))
    item = WebhookInteraction.model_validate(connector.sync_once(dry_run=True).interactions[0]).model_dump(mode="json")
    payload = {"batch_id": "019933f0-0c00-7000-8000-000000000001", "source": "chatlog",
               "interactions": [item], "facts": []}
    assert client.post("/api/v1/webhooks/wechat", json=payload,
                       headers={"X-Webhook-Token": "secret"}).status_code == 200
    return client, repo, store, item


def _upload(client, item, body=b"media-bytes", **overrides):
    digest = hashlib.sha256(body).hexdigest()
    query = {"name": "voice.bin", "message_key": item["source_message_key"]}
    query.update(overrides.pop("query", {}))
    headers = {"X-Webhook-Token": "secret", "X-Content-SHA256": digest,
               "Content-Type": "audio/ogg"}
    headers.update(overrides.pop("headers", {}))
    event_key = overrides.pop("event_key", item["source_event_key"])
    return client.put("/api/v1/webhooks/wechat/media/" + event_key,
                      params=query, content=body, headers=headers)


def test_media_upload_binds_existing_message_and_is_idempotent(tmp_path):
    client, repo, store, item = _fixture(tmp_path)
    first = _upload(client, item)
    assert first.status_code == 200 and first.json()["status"] == "attached"
    second = _upload(client, item)
    assert second.status_code == 200 and second.json()["status"] == "attached"
    interaction = repo.list_interactions()[0]
    assert interaction.message["record"]["content"] == "原文\x00\t 保持完整"
    archive = store.get_record(store.identity("crm", "interactions:" + interaction.id))
    assert archive["raw"]["message"]["record"]["content"] == interaction.message["record"]["content"]
    assert len(archive["assets"]) == 1
    asset = archive["assets"][0]
    assert asset["id"] == hashlib.sha256(b"media-bytes").hexdigest()
    assert asset["name"] == "voice.bin" and asset["media_type"] == "audio/ogg"
    # 周期 collector 和正文重放不清空独立补齐的附件。
    store.ingest("crm", Batch(records=[Record(
        archive["external_id"], "interactions", archive["raw"], archive["normalized"],
        archive["occurred_at"], timezone=archive["timezone"],
    )]))
    assert store.get_record(archive["id"])["assets"] == [asset]
    repo.import_wechat_batch("chatlog", [WebhookInteraction.model_validate(item).model_dump()], [])
    assert store.get_record(archive["id"])["assets"] == [asset]


def test_media_auth_hash_and_missing_message_are_rejected(tmp_path):
    client, _, _, item = _fixture(tmp_path)
    assert _upload(client, item, headers={"X-Webhook-Token": "wrong"}).status_code == 401
    assert _upload(client, item, body=b"different", headers={"X-Content-SHA256": "0" * 64}).status_code == 422
    missing = _upload(client, item, event_key="f" * 64, query={"message_key": "a" * 64})
    assert missing.status_code == 404 and missing.json()["status"] == "pending"


def test_media_tombstone_wins_over_late_upload_and_replay(tmp_path):
    client, repo, store, item = _fixture(tmp_path)
    store.ingest("crm", Batch(deletions=["interactions:" + repo.list_interactions()[0].id]))
    response = _upload(client, item)
    assert response.status_code == 200 and response.json()["status"] == "deleted"
    assert repo.list_interactions() == []
    # A later正文 replay is also ignored by the Hub tombstone.
    replay = client.post("/api/v1/webhooks/wechat", json={
        "batch_id": "019933f0-0c00-7000-8000-000000000002", "source": "chatlog",
        "interactions": [item], "facts": []}, headers={"X-Webhook-Token": "secret"})
    assert replay.status_code == 200 and repo.list_interactions() == []
