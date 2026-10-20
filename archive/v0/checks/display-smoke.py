"""Meaningful display regression tests, using synthetic data only."""
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from fastapi.testclient import TestClient
from personal_data_hub.contracts import Record, Batch
from personal_data_hub.server import create_app
from personal_data_hub.display import Display, index_value
from personal_data_hub.remote import GoogleCollector
from unittest.mock import patch

def time(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
legacy = index_value("health_payloads", "legacy", {}, {"payload": {"steps": 123, "timestamp": "2026-10-06T00:00:00Z", "sleep": None}})
assert legacy["data"]["steps"][0]["value"] == 123 and legacy["data"]["sleep"] == []
assert index_value("health_payloads", "undated", {}, {"payload": {"steps": 123}})["data"]["steps"] == []
with TemporaryDirectory() as temp:
    cfg = {"database_url": "sqlite:///" + temp + "/hub.db", "asset_root": temp + "/assets", "hub_api_token_file": temp + "/writer", "hub_viewer_token_file": temp + "/viewer", "sources": {}}
    Path(cfg["hub_api_token_file"]).write_text("write"); Path(cfg["hub_viewer_token_file"]).write_text("read")
    app = create_app(cfg, webhook_only=True); store = app.state.hub_store
    headers = {"Authorization": "Bearer read"}
    client = TestClient(app)
    def put(src, eid, kind, raw, normal=None, at="2026-10-06T04:00:00Z"):
        return store.ingest(src, Batch(records=[Record(eid, kind, raw, normal or {}, time(at) if at else None)]))
    payload = {"steps": [{"count": 100, "start_time": "2026-10-06T00:00:00+08:00", "end_time": "2026-10-06T12:00:00+08:00"}], "sleep": [{"duration_seconds": 28800, "session_end_time": "2026-10-06T07:00:00+08:00"}]}
    put("health", "one", "health_payloads", {}, {"payload": payload})
    put("health", "two", "health_payloads", {}, {"payload": payload})
    payload2 = json.loads(json.dumps(payload)); payload2["steps"][0]["count"] = 120
    put("health", "three", "health_payloads", {}, {"payload": payload2})
    put("crm", "people:p", "people", {"id": "p", "display_name": "Synthetic Person"})
    for i in range(3): put("crm", "i"+str(i), "interactions", {"person_id": "p", "summary": "test message"})
    put("token", "d1", "token_day", {}, {"tokens": 10, "date": "2026-10-06", "device": "one", "estimated_cost_usd": 1})
    put("token", "d1", "token_day", {}, {"tokens": 20, "date": "2026-10-06", "device": "one", "estimated_cost_usd": 2})
    put("token", "d2", "token_day", {}, {"tokens": 5, "date": "2026-10-06", "device": "two", "estimated_cost_usd": 0.5})
    for i, curr, amount, typ, state in [(1,"CNY","10","Expend","Synced"),(2,"USD","2","Income","Edited"),(3,"CNY","30","Transfer","Synced"),(4,"CNY","7","Expend","Wait2Edit")]:
        put("finance", str(i), "bill", {"currency":curr,"money":amount,"type":typ,"state":state})
    put("skysight", "summary", "computer_summary", {}, {"content": "---\ntitle: readable title\ndescription: bounded text\n---\n"+"x"*900000})
    put("hermes", "unknown", "hermes_execution_report", {}, {"content": "# Unknown time\ntext"}, at=None)
    put("google", "cal", "calendar_event", {"start":{"date":"2026-10-05"},"end":{"date":"2026-10-07"}})
    put("google", "task", "google_task", {"title":"pending","status":"needsAction"})
    params = {"date":"2026-10-06","tz":"Asia/Shanghai","modules":"agenda,health,social,usage,finance,activity"}
    r = client.get("/api/v1/dashboard",params=params,headers=headers)
    assert r.status_code == 200, r.text
    d = {m["id"]:m for m in r.json()["modules"]}
    metrics = lambda m: {v["id"]:v["value"] for v in d[m]["metrics"]}
    assert metrics("health")["steps"] == 120 and metrics("health")["sleep"] == 8
    assert metrics("usage")["tokens"] == 25
    assert metrics("finance")["expense:CNY"] == "10" and metrics("finance")["transfer:CNY"] == "30" and metrics("finance")["income:USD"] == "2"
    assert metrics("social")["people"] == 1 and d["social"]["items"][0]["title"] == "Synthetic Person"
    assert metrics("agenda")["events"] == 1 and metrics("agenda")["tasks"] == 1
    assert len(r.content) < 100000 and "raw" not in r.json()
    assert d["activity"]["items"][0]["title"] == "readable title"
    p = client.get("/api/v1/timeline",params={"limit":2},headers=headers).json()
    ids = [x["id"] for x in p["items"]]
    while p["next_cursor"]:
        p = client.get("/api/v1/timeline",params={"limit":2,"cursor":p["next_cursor"]},headers=headers).json()
        ids += [x["id"] for x in p["items"]]
    assert len(ids) == len(set(ids)) and p["items"][-1]["occurred_at"] is None
    assert client.get("/api/v1/dashboard",params=params).status_code == 401
    for change in ({"tz":"not/a/zone"},{"date":"bad"},{"modules":"bad"}):
        assert client.get("/api/v1/dashboard",params=params|change,headers=headers).status_code == 422
    assert client.get("/api/v1/timeline",params={"cursor":"bad"},headers=headers).status_code == 422
    t=client.get("/api/v1/trends",params=params|{"days":7},headers=headers).json()
    assert len(t["days"])==7 and t["days"][-2]["modules"][1]["metrics"][0]["value"] is None
    assert t["days"][-1]["modules"][0]["metrics"][0]["value"] == 0 # Undated current tasks are not fabricated as historical daily counts.
    store.ingest("health", Batch(deletions=["three"]))
    assert metrics("health")["steps"]==120 # response remains immutable
    assert Display(store).overview("2026-10-06","Asia/Shanghai","health")["modules"][0]["metrics"][0]["value"]==100
    put("health", "sessions", "health_payloads", {}, {"payload": {"sleep": [{"duration_seconds": 3600, "session_end_time": "2026-10-06T06:00:00+08:00"}, {"duration_seconds": 3600, "session_end_time": "2026-10-06T09:00:00+08:00"}]}})
    # A fragment overlapping the overnight session adds nothing; a distinct session adds one hour.
    assert Display(store).overview("2026-10-06","Asia/Shanghai","health")["modules"][0]["metrics"][1]["value"]==9
    put("health", "closed-day", "health_payloads", {}, {"payload": {"steps": [{"count": 200, "start_time": "2026-10-06T00:00:00+08:00", "end_time": "2026-10-07T00:00:00+08:00"}]}})
    assert Display(store).overview("2026-10-06","Asia/Shanghai","health")["modules"][0]["metrics"][0]["value"]==200
    assert store.backfill_display(rebuild=True,kind="health_payloads")==4
    assert store.backfill_display()==0
    class FakeGoogle:
        def __init__(self,*args): pass
        def get(self,url,params):
            if url.endswith("calendarList"): return {"items":[{"id":"email","primary":True,"accessRole":"owner"},{"id":"secondary","accessRole":"owner"},{"id":"shared","accessRole":"reader"}]}
            if "/events" in url:
                assert params["timeMax"] > params["timeMin"]
                return {"items":[{"id":"event","start":{"dateTime":"2026-10-06T12:00:00+08:00"}}]}
            return {"items":[]}
    with patch("personal_data_hub.remote.GoogleReadClient",FakeGoogle):
        batches=list(GoogleCollector({"credential_file":"unused","calendar_scope":"owned"}).collect({}))
        ids=[r.external_id for b in batches for r in b.records]
        assert ids==["calendar:primary:event","calendar:secondary:event"]
print("display_smoke_ok: bounds, health dedup, unknown times, paging, social joins, cumulative token, currency, delete, owned calendars")
