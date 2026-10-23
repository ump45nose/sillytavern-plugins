import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from hub_api.sources.records import health_day

NOW = datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_sleep_overlap_and_missing():
    result = health_day({"date": "2026-10-20", "metrics": {"sleep": {
        "sample_count": 3, "duration_seconds": 27000,
        "stages_seconds": {"deep": 7200}, "awake_seconds": 1800}}})
    assert result["sleep_minutes"] == 450
    assert result["resting_hr"] is None
    assert health_day({"date": "2026-10-20"})["sleep_minutes"] is None


def test_live_shapes_pagination_timezone_and_failure_isolation(settings, caplog):
    settings.records_token = SecretStr("SENTINEL-RECORDS-SECRET")
    calls = []
    health_fails = [False]
    def handle(request):
        assert request.headers["Authorization"] == "Bearer SENTINEL-RECORDS-SECRET"
        calls.append(request.url.path)
        path = request.url.path
        if "/health/" in path:
            if health_fails[0]:
                return httpx.Response(500, text="SENTINEL-RECORDS-SECRET")
            assert path.endswith('/health/summary') and request.url.params['group_by'] == 'date'
            return httpx.Response(200, json={"days": [{"date": "2026-10-20", "metrics": {
                "steps": {"total": 7420}, "active_calories_kcal": {"total": 412},
                "resting_heart_rate": {"latest": {"time": "2026-10-20T01:00:00Z", "bpm": 58}}}}]})
        assert request.url.params["currency"] == "CNY"
        assert request.url.params["type"] == "expense"
        assert request.url.params["status"] == "confirmed"
        if path.endswith("summary"):
            group = request.url.params["group_by"]
            if group == "date":
                return httpx.Response(200, json={"groups": [{"date": "2026-10-20", "amount": "32.10"}, {"date": "2026-10-02", "amount": "100"}]})
            return httpx.Response(200, json={"groups": [{"category": "餐饮", "amount": "32.10"}]})
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json={"records": [{"id": str(offset), "occurred_at": "2026-10-20T01:00:00Z", "amount": "16.05", "item": "午饭"}], "next_offset": 200 if offset == 0 else None})
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        headers = {"Authorization": "Bearer " + settings.dev_token.get_secret_value()}
        response = client.get("/api/v1/modules?ids=health,bills", headers=headers)
        assert response.status_code == 200
        values = response.json()["modules"]
        assert values["health"]["status"] == values["bills"]["status"] == "ok"
        health, bills = values["health"]["data"], values["bills"]["data"]
        assert health["steps"] == 7420 and health["resting_hr"] == 58
        assert len(health["days"]) == 14 and health["days"][0]["date"] == "2026-10-07"
        assert health["days"][0]["steps"] is None
        assert bills["month_total"] == 132.10 and bills["today_total"] == 32.10
        assert len(bills["today_items"]) == 2
        assert bills["today_items"][0]["time"] == "2026-10-20T09:00:00+08:00"
        assert bills["net_worth"] is None
        count = len(calls)
        client.get("/api/v1/modules?ids=health,bills", headers=headers)
        assert len(calls) == count
        health_fails[0] = True
        app = client.app
        app.state.sources.cache.pop("records_health")
        app.state.sources.states.pop("records_health")
        response = client.get("/api/v1/modules?ids=health,bills", headers=headers)
        assert response.json()["modules"]["health"]["status"] == "error"
        assert response.json()["modules"]["bills"]["status"] == "ok"
        assert "SENTINEL-RECORDS-SECRET" not in response.text + caplog.text
