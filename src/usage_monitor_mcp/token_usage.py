from __future__ import annotations

import hashlib
import json
import math
from datetime import timedelta
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .time_window import Window, day_bounds, instant


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def label(value, limit=160):
    return str(value or "unknown")[:limit]


def _dimensions(period, key, cost_key):
    counts, costs = period.get(key, {}), period.get(cost_key, {})
    if not isinstance(counts, dict):
        return []
    if not isinstance(costs, dict):
        costs = {}
    return [{"name": label(k), "tokens": number(v), "estimated_cost_usd": number(costs.get(k))}
            for k, v in counts.items() if number(v) is not None]


def _period(period):
    return {
        "tokens": number(period.get("totalTokens")),
        "estimated_cost_usd": number(period.get("costUsd")),
        "cache_read_tokens": number(period.get("cacheReadTokens")),
        "cache_write_tokens": number(period.get("cacheWriteTokens")),
        "output_tokens": number(period.get("outputTokens")),
        "unclassified_tokens": number(period.get("unclassifiedTokens")),
        "models": _dimensions(period, "models", "modelCosts"),
        "tools": _dimensions(period, "clients", "clientCosts"),
    }


def _history(row):
    result = {
        "tokens": number(row.get("tokens")),
        "estimated_cost_usd": number(row.get("cost")),
        "cache_read_tokens": number(row.get("cacheReadTokens")),
        "cache_write_tokens": number(row.get("cacheWriteTokens")),
        "output_tokens": number(row.get("outputTokens")),
        "unclassified_tokens": number(row.get("unclassifiedTokens")),
    }
    for target, source in (("models", "perModel"), ("tools", "perClient")):
        values = row.get(source, {})
        result[target] = [{"name": label(k), "tokens": number(v.get("tokens")),
                           "estimated_cost_usd": number(v.get("cost"))}
                          for k, v in values.items() if isinstance(v, dict)] if isinstance(values, dict) else []
    return result


def _pick(record, window):
    windows = record.get("periodWindows") or {}
    today = windows.get("today") or {}
    zone = windows.get("timeZone")
    zone_aligned = False
    if zone:
        try:
            start, end = day_bounds(window.day, zone)
            zone_aligned = start == window.start and end == window.day_end
        except (ValueError, KeyError):
            return None, "invalid_device_timezone"
    if zone and not zone_aligned:
        return None, "device_day_boundary_differs"
    if today.get("key") == window.day.isoformat():
        # A matching explicit end also permits old producers without an IANA zone.
        if instant(today.get("endsAt")) != window.day_end:
            return None, "device_day_boundary_unverified"
        periods = record.get("periods") or {}
        if isinstance(periods.get("today"), dict):
            return _period(periods["today"]), "periods.today"
    if not zone_aligned:
        return None, "history_timezone_unverified"
    history = record.get("history") or {}
    rows = history.get("daily", [])
    matches = [r for r in rows if isinstance(r, dict) and r.get("date") == window.day.isoformat()]
    if len(matches) > 1:
        return None, "duplicate_history_dates"
    if matches:
        return _history(matches[0]), "history.daily"
    return None, "no_record_for_requested_date"


def _merge(rows):
    combined = {}
    for row in rows:
        name = row["name"]
        value = combined.setdefault(name, {"name": name, "tokens": 0, "estimated_cost_usd": 0,
                                            "cost_complete": True})
        value["tokens"] += row.get("tokens") or 0
        cost = row.get("estimated_cost_usd")
        if cost is None:
            value["cost_complete"] = False
        else:
            value["estimated_cost_usd"] += cost
    for value in combined.values():
        value["estimated_cost_usd"] = round(value["estimated_cost_usd"], 8) if value["cost_complete"] else None
    return sorted(combined.values(), key=lambda r: (-r["tokens"], r["name"]))


def _limits(records, now, stale_after):
    chosen = {}
    for device_id, record in records.items():
        limit = record.get("limits") or {}
        for p in limit.get("providers", []):
            if not isinstance(p, dict):
                continue
            # Only use the stable provider key; never expose addresses or labels.
            key = (str(p.get("provider") or "unknown"), str(p.get("accountKey") or device_id))
            observed = instant(p.get("updatedAt")) or instant(limit.get("updatedAt"))
            rank = ((p.get("status") == "ok"), observed.timestamp() if observed else 0)
            previous = chosen.get(key)
            if previous is None or rank > previous[0]:
                chosen[key] = (rank, p, observed)
    result = []
    allowed = {"kind", "label", "metric", "used", "remaining", "limit", "usedPercent", "remainingPercent",
               "resetsAt", "boundaryKind", "currency", "showMeter", "source", "limitId", "additional"}
    for key, (_, p, observed) in sorted(chosen.items()):
        result.append({
            "provider": label(key[0]),
            "account_ref": hashlib.sha256((key[0] + "\0" + key[1]).encode()).hexdigest()[:16],
            "status": p.get("status") or "unknown",
            "source": p.get("source") or "unknown",
            "observed_at": observed.isoformat() if observed else None,
            "stale": observed is None or (now - observed).total_seconds() > stale_after,
            "windows": [{k: v for k, v in w.items() if k in allowed and isinstance(v, (str, int, float, bool))}
                        for w in p.get("windows", []) if isinstance(w, dict)],
        })
    return result


def _subscriptions(document):
    doc = document.get("subscriptions")
    if not isinstance(doc, dict):
        return {"status": "unavailable", "records": [], "actual_paid_today": None}
    rows = doc.get("subscriptions")
    if not isinstance(rows, list):
        return {"status": "unavailable", "records": [], "actual_paid_today": None}
    fields = ("provider", "kind", "planName", "amountMinor", "currency", "interval", "intervalCount",
              "startDate", "endDate", "autoRenew", "nextRenewalOverride")
    return {
        "status": "configured" if rows else "not_configured",
        "updated_at": doc.get("updatedAt") or None,
        "records": [{k: r[k] for k in fields if k in r} for r in rows if isinstance(r, dict)],
        "actual_paid_today": None,
        "note": "订阅记录是用户配置的费用；未接入支付流水，不能据此认定当天实际扣款。",
    }


def aggregate_tokens(document, window: Window, stale_after_seconds=600):
    records = document.get("devices")
    if not isinstance(records, dict):
        raise ValueError("Token Monitor devices.json schema invalid")
    devices, models, tools = [], [], []
    for device_id, record in records.items():
        if not isinstance(record, dict):
            continue
        updated = instant(record.get("updatedAt"))
        received = instant(record.get("receivedAt"))
        sync_interval = number(record.get("syncUploadIntervalMs")) or 0
        stale_limit = max(stale_after_seconds, 2 * sync_interval / 1000)
        stale = received is None or (window.generated_at - received).total_seconds() > stale_limit
        windows = record.get("periodWindows") or {}
        entry = {
            "device_id": label(device_id), "source_timezone": windows.get("timeZone"),
            "source_day_key": (windows.get("today") or {}).get("key"),
            "updated_at": record.get("updatedAt"), "received_at": record.get("receivedAt"),
            "stale": stale, "freshness_threshold_seconds": stale_limit,
        }
        usage, basis = _pick(record, window)
        if updated is None or updated > window.generated_at + timedelta(minutes=5):
            usage, basis = None, "source_timestamp_invalid_or_in_future"
        elif usage and updated < window.start:
            usage, basis = None, "source_updated_before_requested_day"
        entry.update({"included": usage is not None and usage.get("tokens") is not None, "basis": basis})
        if entry["included"]:
            entry["data_until"] = min(updated, window.end).isoformat()
            entry["finalized_day"] = updated >= window.day_end
            entry.update({k: v for k, v in usage.items() if k not in ("models", "tools")})
            models.extend(usage["models"])
            tools.extend(usage["tools"])
        else:
            entry.update(tokens=None, estimated_cost_usd=None, data_until=None, finalized_day=False)
        devices.append(entry)
    included = [x for x in devices if x["included"]]
    cost_known = bool(included) and all(x.get("estimated_cost_usd") is not None for x in included)
    exclusions = [x["device_id"] for x in devices if not x["included"]]
    stale_included = any(x["stale"] for x in included)
    totals = {"tokens": sum(x["tokens"] for x in included) if included else None,
              "estimated_cost_usd": round(sum(x["estimated_cost_usd"] for x in included), 8) if cost_known else None,
              "cost_complete": cost_known}
    for field in ("cache_read_tokens", "cache_write_tokens", "output_tokens", "unclassified_tokens"):
        totals[field] = sum(x[field] for x in included) if included and all(x.get(field) is not None for x in included) else None
    return {
        "status": "ok" if included and not exclusions and not stale_included else "partial" if included else "unavailable",
        "totals": totals, "models": _merge(models), "tools": _merge(tools), "devices": devices,
        "coverage": {"included_devices": len(included), "known_devices": len(devices),
                     "excluded_devices": exclusions, "stale_devices": [x["device_id"] for x in devices if x["stale"]]},
        "limits_snapshot": _limits(records, window.generated_at, stale_after_seconds),
        "limits_scope": "生成时的额度状态，不是所查日期的历史额度；缺失状态不等于 0。",
        "subscriptions": _subscriptions(document),
        "cost_basis": "Token Monitor 来源报告的估算美元成本，不代表订阅账单或实际支付。",
        "aggregation_basis": "设备总数相加；模型和工具是同一总数的两个维度，不能再次相加；来源没有跨设备请求 ID，无法排除同一日志在多台机器重复采集。",
        "calendar_basis": "按设备声明的日界线匹配；边界不同或无法核验的设备不进入合计。历史日期只读取精确匹配的 history.daily 行。",
    }


def _read_stats(settings):
    if not settings.token_stats_url:
        return None, "not_configured"
    parsed = urlsplit(settings.token_stats_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        return None, "invalid_configuration"
    try:
        from pathlib import Path
        secret = Path(settings.token_secret_file).read_text().strip()
        if not secret or "\n" in secret or "\r" in secret:
            return None, "invalid_secret_file"
        request = Request(settings.token_stats_url, headers={"Authorization": "Bearer " + secret,
                                                            "Accept": "application/json"})
        # The NAS API is private; avoid forwarding its bearer to an outbound proxy.
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=8) as response:
            body = response.read(16_000_001)
            if len(body) > 16_000_000:
                return None, "response_too_large"
            return json.loads(body), "ok"
    except Exception as error:
        # Exception text may carry URLs. Only return its class.
        return None, type(error).__name__


def read_tokens(settings, window):
    try:
        with settings.token_data_file.open() as handle:
            document = json.load(handle)
        stale_after = settings.token_stale_after_seconds
        stats, api_status = _read_stats(settings)
        if isinstance(stats, dict) and number(stats.get("staleAfterMs")):
            stale_after = stats["staleAfterMs"] / 1000
        result = aggregate_tokens(document, window, stale_after)
        if isinstance(stats, dict) and isinstance(stats.get("limits"), dict):
            result["limits_snapshot"] = _limits({"hub": {"limits": stats["limits"]}}, window.generated_at, stale_after)
        result["source"] = "token-monitor/devices.json"
        result["stats_api_status"] = api_status
        result["freshness_configuration"] = "authenticated_api" if stats else "configured_fallback"
        return result
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {"status": "unavailable", "source": "token-monitor/devices.json",
                "error": type(error).__name__, "totals": {"tokens": None, "estimated_cost_usd": None},
                "models": [], "tools": [], "devices": [], "limits_snapshot": [],
                "subscriptions": {"status": "unavailable", "records": [], "actual_paid_today": None}}
