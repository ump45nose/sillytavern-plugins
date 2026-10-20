from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from hub_api.settings import Settings
from hub_api.sources.base import Adapter, SourceManager




def test_auth_devices_and_safe_errors(settings, caplog):
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/v1/status").status_code == 401
        pair = app.state.store.issue_device("Mac", datetime.now(ZoneInfo("Asia/Shanghai")).isoformat())
        headers = {"Authorization": "Bearer " + pair["token"]}
        assert client.get("/api/v1/status", headers=headers).status_code == 200
        with app.state.store.connection() as db:
            assert pair["token"] not in str([tuple(r) for r in db.execute("SELECT * FROM devices")])
        response = client.get("/api/v1/devices", headers=headers)
        assert pair["token"] not in response.text
        assert client.delete("/api/v1/devices/" + pair["device_id"], headers=headers).status_code == 204
        assert client.get("/api/v1/status", headers=headers).status_code == 401
        assert settings.dev_token.get_secret_value() not in caplog.text


async def test_cache_isolation_expiry_and_sanitized_failure():
    clock = [datetime(2026, 10, 20, 12, tzinfo=ZoneInfo("Asia/Shanghai"))]
    failing = [False]
    calls = []
    async def fetch():
        calls.append(1)
        if failing[0]:
            request = httpx.Request("GET", "http://test/SENTINEL")
            response = httpx.Response(502, request=request, text="SENTINEL")
            response.raise_for_status()
        return {"value": 42}
    manager = SourceManager([Adapter("a", "A", 60, fetch), Adapter("b", "B", 60)], lambda: clock[0])
    assert (await manager.get("a"))["status"] == "ok"
    failing[0] = True
    assert (await manager.get("a"))["status"] == "ok"
    assert len(calls) == 1
    clock[0] += timedelta(seconds=61)
    result = await manager.get("a")
    assert result["status"] == "stale" and result["data"]["value"] == 42
    assert manager.status("a")["last_error"] == {"type": "http_status", "status_code": 502}
    assert (await manager.get("b"))["status"] == "unconfigured"
    clock[0] += timedelta(hours=24)
    assert (await manager.get("a"))["status"] == "error"


def test_batch_and_secret_redaction(settings):
    async def source(): return {"value": settings.dev_token.get_secret_value()}
    from hub_api.modules import MODULE_SOURCES
    adapters = [Adapter(s, s, 60, source if s == "records_health" else None)
                for s in dict.fromkeys(s for ids in MODULE_SOURCES.values() for s in ids)]
    with TestClient(create_app(settings, adapters=adapters)) as client:
        headers = {"Authorization": "Bearer " + settings.dev_token.get_secret_value()}
        response = client.get("/api/v1/modules?ids=health,bills", headers=headers)
        assert response.status_code == 200
        assert response.json()["modules"]["health"]["status"] == "ok"
        assert response.json()["modules"]["bills"]["status"] == "unconfigured"
        assert settings.dev_token.get_secret_value() not in response.text
        assert client.get("/api/v1/modules?ids=unknown", headers=headers).status_code == 400


async def test_timeout_isolated_and_same_source_deduplicated():
    import asyncio
    clock = lambda: datetime.now(ZoneInfo("Asia/Shanghai"))
    calls = []
    async def slow():
        await asyncio.sleep(1)
        return {"value": 1}
    async def fast():
        calls.append(1)
        await asyncio.sleep(0.001)
        return {"value": 2}
    manager = SourceManager([Adapter("slow", "S", 60, slow), Adapter("fast", "F", 60, fast)], clock, 0.02)
    results = await asyncio.gather(manager.get("slow"), manager.get("fast"), manager.get("fast"))
    assert [r["status"] for r in results] == ["error", "ok", "ok"]
    assert len(calls) == 1
    assert manager.status("slow")["last_error"]["type"] == "timeout"
