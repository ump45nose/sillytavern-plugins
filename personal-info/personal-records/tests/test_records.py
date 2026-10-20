import asyncio
import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client
from mcp_platform import RuntimeConfig, authorize

from personal_records import adapters
from personal_records.api import create_app
from personal_records.mcp import create_mcp
from personal_records.migration import Audit, import_rows
from personal_records.models import Conflict, NotFound
from personal_records.service import Service
from personal_records.settings import Settings
from personal_records.store import Store


def native_health():
    return {"timestamp": "2026-10-16T08:00:00Z", "app_version": "1.9.14",
        "steps": [{"start_time": "2026-10-14T16:00:00Z", "end_time": "2026-10-15T16:00:00Z", "count": 8000}],
        "heart_rate": [{"time": "2026-10-15T01:00:00Z", "bpm": 60, "metadata": {"data_origin": "ring", "device": {"type": 4}}}],
        "sleep": [{"session_end_time": "2026-10-14T23:00:00Z", "duration_seconds": 32400,
            "stages": [
                {"start_time": "2026-10-14T14:00:00Z", "end_time": "2026-10-14T16:00:00Z", "stage": 4},
                {"start_time": "2026-10-14T16:00:00Z", "end_time": "2026-10-14T16:30:00Z", "stage": 1},
                {"start_time": "2026-10-14T16:30:00Z", "end_time": "2026-10-14T23:00:00Z", "stage": 5}],
            "metadata": {"data_origin": "ring"}}]}


def native_bill(id=1, amount="0.1", state="Synced", currency="CNY", type="Expend"):
    return {"id": id, "time": 1760000000123, "money": amount, "fee": "0.01", "currency": currency,
        "type": type, "state": state, "cateName": "food", "accountNameFrom": "wallet", "bookName": "daily",
        "shopName": "shop", "remark": "meal", "tags": '["lunch"]', "ruleName": "private rule", "rawAccountNameFrom": "raw"}


@pytest.fixture
def service(tmp_path):
    return Service(Store(tmp_path/"records.sqlite"))


@pytest.fixture
def settings(tmp_path):
    return Settings(str(tmp_path/"api.sqlite"), RuntimeConfig(name="test", development_no_auth=True), "reader", "writer", "health", "accounting")


def test_partial_ingestion_dedup_and_source_heartbeat(service):
    first = service.store.ingest("health", native_health())
    original = service.get_health_day("2026-10-15")
    assert first["created"] == 1
    assert "timestamp" not in original and "app_version" not in original
    assert service.store.ingest("health", native_health())["unchanged"] == 1
    assert service.get_health_day("2026-10-15")["updated_at"] == original["updated_at"]
    partial = {"heart_rate": [{"time": "2026-10-15T02:00:00Z", "bpm": 66}]}
    service.store.ingest("health", partial)
    record = service.get_health_day("2026-10-15")
    assert record["steps"] == 8000 and len(record["heart_rate"]) == 2 and len(record["sleep"]) == 3
    assert service.store.source_status()[0]["last_received_at"]


def test_sleep_ownership_stage_mapping_and_summary(service):
    service.store.ingest("health", native_health())
    assert service.list_health_days()["records"][0]["date"] == "2026-10-15"
    with pytest.raises(NotFound): service.get_health_day("2026-10-14")
    metrics = service.health_summary("2026-10-15", "2026-10-16")["metrics"]
    assert metrics["sleep"]["session_seconds"] == 9*3600
    assert metrics["sleep"]["duration_seconds"] == 8.5*3600
    assert metrics["sleep"]["stages_seconds"]["awake"] == 1800
    assert metrics["total_calories_kcal"]["total"] is None


def test_interval_union_and_exercise_business_fields(service):
    service.store.ingest("health", {"exercise": [
        {"start_time": "2026-10-15T01:00:00Z", "end_time": "2026-10-15T02:00:00Z", "type": "79", "steps": 500, "avg_cadence_spm": 88},
        {"start_time": "2026-10-15T01:30:00Z", "end_time": "2026-10-15T02:30:00Z", "type": "79"}]})
    assert service.health_summary("2026-10-15", "2026-10-15")["metrics"]["exercise"]["duration_seconds"] == 5400
    assert service.get_health_day("2026-10-15")["exercise"][0]["steps"] == 500


def test_crud_arrays_replace_source_merges_and_delete_recreates(service):
    service.store.ingest("health", native_health())
    service.update_health_day("2026-10-15", {"heart_rate": [], "steps": 0})
    assert service.get_health_day("2026-10-15")["heart_rate"] == []
    assert len(service.get_health_day("2026-10-15")["sleep"]) == 3
    service.update_health_day("2026-10-15", {"steps": None})
    assert "steps" not in service.get_health_day("2026-10-15")
    service.store.ingest("health", native_health())
    assert service.get_health_day("2026-10-15")["steps"] == 8000
    service.delete_health_day("2026-10-15")
    assert service.store.ingest("health", native_health())["created"] == 1


def test_source_correction_and_origin_device_identity(service):
    source = native_health()
    service.store.ingest("health", source)
    source["steps"][0]["count"] = 7000
    source["heart_rate"][0]["bpm"] = 72
    service.store.ingest("health", source)
    assert service.get_health_day("2026-10-15")["steps"] == 7000
    assert len(service.get_health_day("2026-10-15")["heart_rate"]) == 1
    source["heart_rate"][0]["metadata"]["device"]["type"] = 5
    service.store.ingest("health", source)
    assert len(service.get_health_day("2026-10-15")["heart_rate"]) == 2


def test_atomic_rejection_and_boolean_validation(service):
    invalid = native_health()
    invalid["heart_rate"][0]["bpm"] = True
    with pytest.raises(ValueError): service.store.ingest("health", invalid)
    assert service.list_health_days()["records"] == []
    assert service.store.source_status()[0]["last_received_at"] is None
    service.create_health_day({"date": "2026-10-15", "steps": 0})
    with pytest.raises(ValueError): service.update_health_day("2026-10-15", {"steps": True})


def test_concurrent_partial_updates_do_not_lose_samples(service):
    def ingest(i):
        service.store.ingest("health", {"heart_rate": [{"time": f"2026-10-15T01:{i:02d}:00Z", "bpm": 60+i}]})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(ingest, range(32)))
    assert len(service.get_health_day("2026-10-15")["heart_rate"]) == 32


def test_bill_normalization_identity_update_and_business_pruning(service):
    source = native_bill(currency='{"code":"CNY","rate":1,"baseCurrency":"CNY","timestamp":123}')
    assert service.store.ingest("autoaccounting", source)["created"] == 1
    record = service.list_bills()["records"][0]
    assert record["currency"] == "CNY" and record["type"] == "expense"
    assert record["tags"] == ["lunch"] and record["source_id"] == "1"
    assert "ruleName" not in record and "rawAccountNameFrom" not in record
    source["money"] = "0.2"
    service.store.ingest("autoaccounting", source)
    assert service.list_bills()["records"][0]["id"] == record["id"]
    assert service.get_bill(record["id"])["amount"] == "0.2"
    assert service.store.ingest("autoaccounting", source)["unchanged"] == 1


def test_exact_money_currency_types_pending_and_grouping(service):
    for source in (native_bill(1, "0.1"), native_bill(2, "0.2"), native_bill(3, "9007199254740993.01", state="Wait2Edit"), native_bill(4, "2.5", currency="USD", type="IncomeRefund")):
        service.store.ingest("autoaccounting", source)
    summary = service.bill_summary("2025-10-01", "2025-10-31", group_by="category")
    assert summary["count"] == 3 and summary["pending_count"] == 1
    assert summary["totals"][0] == {"currency": "CNY", "type": "expense", "amount": "0.3", "fee": "0.02", "count": 2}
    assert summary["totals"][1]["type"] == "income_refund"
    assert summary["groups"][0]["category"] == "food"
    pending = service.bill_summary("2025-10-01", "2025-10-31", status="pending")
    assert pending["totals"][0]["amount"] == "9007199254740993.01"


def test_inclusive_date_boundary_and_filter_parity(service):
    for stamp in ("2026-10-15T23:59:59.999999+08:00", "2026-10-16T00:00:00.000001+08:00"):
        service.create_bill({"occurred_at": stamp, "type": "expense", "amount": "1", "currency": "CNY", "category": "a", "merchant": "Shop"})
    filters = dict(start_date="2026-10-15", end_date="2026-10-15", category="a", query="shop")
    assert len(service.list_bills(**filters)["records"]) == 1
    assert service.bill_summary(**filters)["count"] == 1


def test_pagination_missing_and_conflicts(service):
    for selected in ("2026-10-14", "2026-10-15", "2026-10-16"):
        service.create_health_day({"date": selected, "steps": 1, "heart_rate": []})
    first = service.list_health_days(limit=2)
    assert first["next_offset"] == 2 and "heart_rate" not in first["records"][0]
    assert service.list_health_days(offset=2, limit=2)["next_offset"] is None
    with pytest.raises(Conflict): service.create_health_day({"date": "2026-10-15"})
    for kwargs in ({"limit": 201}, {"offset": -1}):
        with pytest.raises(ValueError): service.list_health_days(**kwargs)
    with pytest.raises(ValueError): service.health_summary("2026-10-16", "2026-10-15")


def test_sqlite_backup_includes_wal(service, tmp_path):
    service.create_health_day({"date": "2026-10-15", "steps": 12})
    target = tmp_path/"backup.sqlite"
    service.store.backup(target)
    assert Store(target).get_health("2026-10-15")["steps"] == 12


def test_http_auth_atomic_ack_and_no_legacy_routes(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/sources").status_code == 401
        assert client.get("/api/v1/sources", headers={"Authorization": "Bearer health"}).status_code == 401
        assert client.post("/webhooks/health", json=native_health(), headers={"Authorization": "Bearer writer"}).status_code == 401
        source_auth = {"Authorization": "Bearer health"}
        assert client.post("/webhooks/health", json=native_health(), headers=source_auth).json()["committed"] is True
        read = {"Authorization": "Bearer reader"}
        assert client.get("/api/v1/health/days/2026-10-15", headers=read).json()["steps"] == 8000
        assert client.delete("/api/v1/health/days/2026-10-15", headers=read).status_code == 403
        assert client.post("/health/import", json={}, headers=source_auth).status_code == 404
        assert client.get("/openapi.json").json()["components"]["schemas"]["HealthDay"]
        invalid = client.post("/webhooks/health", content='{"heart_rate":[{"time":"2026-10-15T01:00:00Z","bpm":NaN}]}', headers={**source_auth, "Content-Type": "application/json"})
        assert invalid.status_code == 422


def test_http_decimal_native_json_and_crud(settings):
    with TestClient(create_app(settings)) as client:
        raw = json.dumps(native_bill()).replace('"0.1"', '9007199254740993.01')
        response = client.post("/webhooks/autoaccounting", content=raw, headers={"Authorization": "Bearer accounting", "Content-Type": "application/json"})
        assert response.status_code == 200, response.text
        read, write = {"Authorization": "Bearer reader"}, {"Authorization": "Bearer writer"}
        records = client.get("/api/v1/bills", headers=read).json()["records"]
        assert records[0]["amount"] == "9007199254740993.01"
        identifier = records[0]["id"]
        assert client.patch(f"/api/v1/bills/{identifier}", json={"note": "edited"}, headers=write).json()["note"] == "edited"
        result = client.get("/api/v1/bills/summary?start_date=2025-10-01&end_date=2025-10-31", headers=read)
        assert result.status_code == 200 and result.json()["count"] == 1
        assert client.delete(f"/api/v1/bills/{identifier}", headers=write).json()["deleted"] is True


def test_mcp_crud_and_summary_share_http_service(service, settings):
    async def run():
        async with Client(create_mcp(service, settings.runtime)) as client:
            tools = await client.list_tools()
            assert len(tools) == 13
            await client.call_tool("create_health_day", {"record": {"date": "2026-10-15", "steps": 10}})
            got = await client.call_tool("get_health_day", {"date": "2026-10-15"})
            assert got.data["steps"] == service.get_health_day("2026-10-15")["steps"]
            await client.call_tool("update_health_day", {"date": "2026-10-15", "patch": {"steps": 20}})
            summary = await client.call_tool("summarize_health", {"start_date": "2026-10-15", "end_date": "2026-10-15"})
            assert summary.data == service.health_summary("2026-10-15", "2026-10-15")
            bill = await client.call_tool("create_bill", {"record": {"occurred_at": "2026-10-15T01:00:00Z", "amount": "1.20", "currency": "CNY", "type": "expense"}})
            await client.call_tool("update_bill", {"id": bill.data["id"], "patch": {"amount": "2.30"}})
            listing = await client.call_tool("list_bills", {})
            assert listing.data["records"][0]["amount"] == "2.30"
            await client.call_tool("delete_bill", {"id": bill.data["id"]})
            await client.call_tool("delete_health_day", {"date": "2026-10-15"})
    asyncio.run(run())


def test_shared_oauth_read_only_permission():
    config = RuntimeConfig(name="test", public_base_url="https://records.example.com", oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration", oidc_client_id="records", oidc_client_secret="secret", jwt_signing_key="a"*32, storage_encryption_key="b"*32, authorized_usernames={"reader", "owner"}, read_only_usernames={"reader"})
    for user, writable in (("reader", False), ("owner", True)):
        ctx = SimpleNamespace(token=SimpleNamespace(claims={"preferred_username": user}))
        assert authorize("read", config)(ctx) is True
        assert authorize("write", config)(ctx) is writable


def test_migration_reconstruction_and_independent_tamper_detection(service, tmp_path):
    audit = Audit(tmp_path/"audit.sqlite")
    rows = [{"source": "health", "external_id": "old:1", "raw": {"payload_json": native_health()}, "observed_at": datetime.now(timezone.utc)},
            {"source": "health", "external_id": "old:2", "raw": {"payload_json": native_health()}, "observed_at": datetime.now(timezone.utc)},
            {"source": "finance", "external_id": "1", "raw": {"bill": native_bill()}, "observed_at": datetime.now(timezone.utc)}]
    counts = import_rows(iter(rows), service.store, audit)
    result = audit.verify(service.store)
    assert counts == {"health": 2, "finance": 1} and result["health_days"] == 1 and result["bills"] == 1
    service.update_health_day("2026-10-15", {"steps": 999})
    with pytest.raises(ValueError): audit.verify(service.store)
    audit.close()


def test_legacy_huawei_steps_only_are_audited(tmp_path):
    from personal_records.migration import Audit, import_rows
    store = Store(tmp_path/'legacy.sqlite')
    audit = Audit(tmp_path/'audit.sqlite')
    rows = [{'source': 'health', 'external_id': 'huawei', 'observed_at': '2026-07-17T00:00:00Z', 'raw': {'payload_json': {'date': '2026-07-17T00:00:00+08:00', 'steps': 123, 'weight_kg': 70, 'sleep_minutes': 480, 'heart_rate_avg': 60}}}]
    counts = import_rows(rows, store, audit)
    assert counts['legacy_unmigrated_sleep_minutes'] == 1
    assert store.get_health('2026-07-17')['steps'] == 123
    assert 'sleep' not in store.get_health('2026-07-17')
    assert audit.verify(store)['verified']
    audit.close()


def test_sleeping_envelope_excludes_overlapping_awake_intervals(service):
    service.create_health_day({"date": "2026-10-18", "sleep": [
        {"start": "2026-10-17T22:00:00Z", "end": "2026-10-18T06:00:00Z", "stage": "sleeping"},
        {"start": "2026-10-17T22:30:00Z", "end": "2026-10-18T00:00:00Z", "stage": "light"},
        {"start": "2026-10-17T23:00:00Z", "end": "2026-10-17T23:30:00Z", "stage": "awake"},
        {"start": "2026-10-18T01:00:00Z", "end": "2026-10-18T01:15:00Z", "stage": "awake_in_bed"},
        {"start": "2026-10-18T05:50:00Z", "end": "2026-10-18T06:10:00Z", "stage": "out_of_bed"},
        {"start": "2026-10-17T21:00:00Z", "end": "2026-10-17T22:00:00Z", "stage": "unknown"},
    ]})
    sleep = service.health_summary("2026-10-18", "2026-10-18")["metrics"]["sleep"]
    assert sleep["duration_seconds"] == 8 * 3600 - 55 * 60
    assert sleep["session_seconds"] == 9 * 3600 + 10 * 60
    assert sleep["sample_count"] == 6
    assert sleep["stages_seconds"]["awake"] == 30 * 60
