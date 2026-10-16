"""Remaining Hub display modules and retired-source boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from personal_data_hub.contracts import Record, Batch, instant
from personal_data_hub.server import create_app
from personal_data_hub.display import index_value

assert index_value("health_payloads", "old", {}, {}) ["domain"] == "technical"
assert index_value("bill", "old", {}, {}) ["domain"] == "technical"
with TemporaryDirectory() as temp:
    Path(temp+"/read").write_text("read")
    cfg = {"database_url": "sqlite:///"+temp+"/hub.db", "asset_root": temp+"/assets", "hub_viewer_token_file": temp+"/read", "sources": {"sky": {"adapter": "skysight"}}}
    app = create_app(cfg, webhook_only=True)
    store = app.state.hub_store
    for i in range(3):
        store.ingest("sky", Batch(records=[Record(str(i), "computer_summary", {}, {"content": "---\ntitle: readable title\n---\n"+"x"*900000}, instant("2026-10-06T04:00:00Z"))]))
    client = TestClient(app)
    h = {"Authorization": "Bearer read"}
    params = {"date": "2026-10-06", "tz": "Asia/Shanghai", "modules": "activity"}
    r = client.get("/api/v1/dashboard", params=params, headers=h)
    assert r.status_code == 200 and len(r.content) < 100000
    assert r.json()["modules"][0]["items"][0]["title"] == "readable title"
    for retired in ("health", "finance"):
        assert client.get("/api/v1/dashboard", params=params|{"modules": retired}, headers=h).status_code == 422
    for path in ("/health", "/health/import", "/autoaccounting/v1/bills"):
        assert client.post(path, json={}, headers=h).status_code == 404
    assert client.get("/api/v1/dashboard", params=params).status_code == 401
    ids, cursor = [], None
    while True:
        page = client.get("/api/v1/timeline", params={"limit": 2, **({"cursor": cursor} if cursor else {})}, headers=h).json()
        ids.extend(x["id"] for x in page["items"])
        cursor = page["next_cursor"]
        if not cursor: break
    assert len(ids) == len(set(ids)) == 3
print("display_smoke_ok")
