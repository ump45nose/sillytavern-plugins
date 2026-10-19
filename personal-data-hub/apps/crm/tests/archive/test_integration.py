from datetime import datetime
from fastapi.testclient import TestClient
from personal_crm.app.settings import Settings
from personal_crm.events import ChatEventProducer
from personal_data_hub.server import create_app
from personal_data_hub.storage import Store
from personal_crm.archive.models import metadata
from .test_archive import msg
import pytest


def test_hub_auth_no_mirror_daily_reading(tmp_path):
    config = {
        "database_url": "sqlite:///" + str(tmp_path / "hub.db"),
        "asset_root": str(tmp_path / "assets"),
        "sources": {},
        "hub_api_token": "writer",
        "hub_viewer_token": "reader",
    }
    for role in ("api", "viewer"):
        path = tmp_path / (role + ".token")
        path.write_text("writer" if role == "api" else "reader")
        config["hub_" + role + "_token_file"] = str(path)
    store = Store(config["database_url"], config["asset_root"])
    metadata.create_all(store.engine)
    with TestClient(
        create_app(
            config, Settings(mcp_development_no_auth=True, wechat_webhook_secret="collector")
        )
    ) as c:
        assert (
            c.post(
                "/api/v1/crm/ingest/wechat",
                headers={"X-Webhook-Token": "collector"},
                json={"messages": [msg()]},
            ).status_code
            == 200
        )
        assert (
            c.get("/api/v1/crm/people", headers={"Authorization": "Bearer reader"}).status_code
            == 200
        )
        assert (
            c.post(
                "/api/v1/crm/people",
                headers={"Authorization": "Bearer reader"},
                json={"name": "bad"},
            ).status_code
            == 401
        )
        response = c.get(
            "/api/v1/daily-push?day=2026-10-15", headers={"Authorization": "Bearer reader"}
        )
        assert response.status_code == 200
        assert "原文" in response.json()["crm"]["contacts"][0]["messages"][0]["text"]
        assert store.list_records(source="crm") == []


@pytest.mark.asyncio
async def test_chat_event_uses_editable_archive(archive, tmp_path):
    class Events:
        def register_event(self, *a, **k):
            pass

        async def publish(self, *a, **k):
            return {"queued": 1}

    archive.ingest_wechat({"messages": [msg()]})
    iid = archive.list_interactions()["items"][0]["id"]
    archive.update_interaction(iid, {"content": "用户改过的正文"})
    producer = ChatEventProducer(
        archive, Events(), owner="owner", storage_path=str(tmp_path / "reports")
    )
    result = await producer.run_once(datetime.fromisoformat("2026-10-15T23:00:05+08:00"))
    page = producer.read_page(result["report_id"], subject="owner")
    assert page["records"][0]["content"] == "用户改过的正文"


def test_shared_blob_survives_hub_record_deletion(tmp_path):
    import base64
    from personal_crm.archive import Archive
    from personal_data_hub.contracts import Asset, Batch, Record

    store = Store("sqlite:///" + str(tmp_path / "hub.db"), tmp_path / "assets")
    archive = Archive(engine=store.engine, asset_root=store.root, asset_lock=store.writer_lock)
    store.register("test", "owner", "bills", "explicit_only")
    content = b"shared existing file"
    store.ingest("test", Batch(records=[Record("one", "bill", {}, assets=[Asset("file.txt", content=content)])]))
    uploaded = archive.upload_attachment("file.txt", "text/plain", [content])
    store.ingest("test", Batch(deletions=["one"]))
    assert not store.list_records()
    assert base64.b64decode(archive.read_attachment(uploaded["id"])["base64"]) == content
    assert list(store.root.glob("??/" + "?" * 64))
