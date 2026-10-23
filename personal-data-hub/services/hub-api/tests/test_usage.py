from datetime import timedelta

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from hub_api.modules.token import assemble
from test_records import NOW


def test_rolling_ranges_unknown_buckets_and_previous_period():
    source = {"today": {"total": 100, "cost": 1}, "tools": [{"id": "codex", "name": "Codex", "total": 100}],
              "devices": [], "limits": [], "daily": {(NOW.date() - timedelta(days=i)).isoformat(): {"total": i, "cost": 0.1} for i in range(1, 800)}}
    week = assemble(source, "week", NOW)
    assert week["total"] == 121 and week["previous"] == sum(range(7, 14))
    assert len(week["buckets"]["series"]) == 7
    assert all(v is None for row in week["buckets"]["series"] for v in row["values"])
    assert week["tools"] is None
    assert assemble(source, "month", NOW)["buckets"] is None
    year = assemble(source, "year", NOW)
    assert len(year["buckets"]["series"][0]["values"]) == 371
    assert year["period"]["start"] == "2025-10-20"
    assert year["buckets"]["series"][0]["values"][-1] is None
    source["daily"].pop((NOW.date() - timedelta(days=2)).isoformat())
    assert assemble(source, "week", NOW)["total"] is None


def test_token_net_fake_sources_ranges_and_partial(settings):
    settings.token_secret = SecretStr("SENTINEL-TOKEN")
    settings.usage_token = SecretStr("SENTINEL-USAGE")
    def handle(request):
        if request.url.path == "/api/stats":
            return httpx.Response(200, json={"periods": {"today": {"totalTokens": 100, "costUsd": 1, "clients": {"codex": 100}}},
                 "devices": [{"deviceId": "mac", "hostname": "Mac", "periods": {"today": {"totalTokens": 100}}}],
                 "historyPreview": {"daily": [{"date": "2026-10-19", "tokens": 10, "cost": 0.1}]},
                 "limits": {"providers": [{"provider": "codex", "status": "ok", "planLabel": "Pro", "accountKey": "private", "windows": [{"label": "5h", "usedPercent": 86}]}]}})
        if request.url.path == '/api/history':
            return httpx.Response(200, json={'daily': [{'date': '2026-10-19', 'tokens': 10, 'cost': .1}]})
        if request.url.path == '/api/devices':
            return httpx.Response(200, json={'devices': []})
        return httpx.Response(200, json={"data": {"pools": None, "today": {"up_bytes": 10, "down_bytes": 20}, "month_bytes": 30, "hourly": []}, "gaps": ["quotas_unavailable"]})
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        headers = {"Authorization": "Bearer " + settings.dev_token.get_secret_value()}
        values = client.get("/api/v1/modules?ids=token,net", headers=headers).json()["modules"]
        assert values["token"]["status"] == "ok" and values["token"]["data"]["total"] == 100
        assert values["token"]["data"]["limits"][0]["windows"][0]["percent"] == 86
        assert values["net"]["status"] == "partial" and values["net"]["data"]["pools"] == []
        month = client.get("/api/v1/modules/token?range=month", headers=headers).json()
        assert month["data"]["range"] == "month" and month["data"]["total"] is None
        assert "accountKey" not in str(month)
        assert client.get("/api/v1/modules/token?range=invalid", headers=headers).status_code == 400
