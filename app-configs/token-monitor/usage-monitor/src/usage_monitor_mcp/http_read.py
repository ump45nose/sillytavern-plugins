"""Owner-scoped read HTTP routes, alongside the existing OAuth MCP surface."""
from __future__ import annotations

import asyncio
import hmac
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from starlette.responses import JSONResponse

from .token_usage import _read_stats, _limits


def network_snapshot(settings, now=None):
    now = (now or datetime.now(ZoneInfo(settings.traffic_timezone))).astimezone(ZoneInfo(settings.traffic_timezone))
    today = datetime.combine(now.date(), time.min, now.tzinfo)
    start = today.replace(day=1)
    end = today + timedelta(days=1)
    db = sqlite3.connect(settings.traffic_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        rows = db.execute("SELECT substr(bucket,1,13),SUM(upload_bytes),SUM(download_bytes) FROM traffic_hourly "
                          "WHERE bucket>=? AND bucket<? GROUP BY substr(bucket,1,13)",
                          (start.strftime("%Y-%m-%dT%H:%M"), end.strftime("%Y-%m-%dT%H:%M"))).fetchall()
        last = db.execute("SELECT value FROM collector_meta WHERE key='last_sample'").fetchone()
    finally:
        db.close()
    # Missing fact hours are unknown, not zero. Never use the rolling JSON export as today's traffic.
    current_key = now.strftime("%Y-%m-%dT%H")
    rows = [(key, up, down) for key, up, down in rows if key <= current_key]
    today_rows = [(up, down) for key, up, down in rows if key[:10] == today.date().isoformat()]
    by_hour = {key: up + down for key, up, down in rows}
    return {"data": {
        # The collector has route classes, not subscription quota/expiry facts.
        "pools": None,
        "today": {"up_bytes": sum(r[0] for r in today_rows) if today_rows else None,
                  "down_bytes": sum(r[1] for r in today_rows) if today_rows else None},
        "month_bytes": sum(up + down for _, up, down in rows) if rows else None,
        "hourly": [{"hour": (h := today + timedelta(hours=i)).isoformat(),
                    "bytes": by_hour.get(h.strftime("%Y-%m-%dT%H")) if h <= now else None} for i in range(24)]},
        "updated_at": last[0] if last else None,
        "gaps": ["subscription_quotas_unavailable", "missing_hours_are_unknown"]}


def attach_read_routes(server, settings):
    # Optional configuration preserves current MCP operation when the HTTP token is absent.
    token = Path(settings.http_read_token_file).read_text().strip() if settings.http_read_token_file else ""
    if settings.http_read_token_file and not token:
        raise ValueError("empty HTTP read credential")

    def rejected(request):
        if not token:
            return JSONResponse({"error": {"code": "unconfigured"}}, status_code=503)
        header = request.headers.get("authorization", "")
        if not hmac.compare_digest(header.encode(), ("Bearer " + token).encode()):
            return JSONResponse({"error": {"code": "unauthorized"}}, status_code=401)
        return None

    @server.custom_route("/api/v1/net", methods=["GET"])
    async def net(request):
        rejection = rejected(request)
        if rejection is not None:
            return rejection
        try:
            return JSONResponse(await asyncio.to_thread(network_snapshot, settings))
        except (OSError, sqlite3.Error, ValueError):
            return JSONResponse({"error": {"code": "source_unavailable"}}, status_code=502)

    @server.custom_route("/api/v1/limits", methods=["GET"])
    async def limits(request):
        rejection = rejected(request)
        if rejection is not None:
            return rejection
        stats, status = await asyncio.to_thread(_read_stats, settings)
        if not isinstance(stats, dict) or not isinstance(stats.get("limits"), dict):
            return JSONResponse({"error": {"code": "source_unavailable"}}, status_code=502)
        now = datetime.now(ZoneInfo(settings.timezone))
        stale = stats.get("staleAfterMs", settings.token_stale_after_seconds * 1000) / 1000
        values = _limits({"hub": {"limits": stats["limits"]}}, now, stale)
        return JSONResponse({"limits": values, "updated_at": stats["limits"].get("updatedAt")})
