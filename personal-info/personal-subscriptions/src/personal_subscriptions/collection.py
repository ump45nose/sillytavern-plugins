import fcntl
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .models import Reading, Window
from .exchange import refresh
from .network_quota import QuotaError, fetch_userinfo


class CollectionError(Exception): pass


def instant(value):
    if not value: raise CollectionError("missing_observation_time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise CollectionError("invalid_observation_time")
    return parsed


def match_account(binding, providers):
    candidates = [p for p in providers if p.get("provider") == binding["provider"]]
    exact = [p for p in candidates if binding["account"] in
             [p.get("accountKey"), p.get("webAccountKey"), *(p.get("accountKeyAliases") or [])]]
    if len(exact) == 1: return exact[0]
    if len(exact) > 1: raise CollectionError("ambiguous_account")
    email = binding.get("account_email", "").casefold()
    if email:
        exact = [p for p in candidates if (p.get("accountEmail") or "").casefold() == email]
        if len(exact) == 1: return exact[0]
    profile = binding.get("profile")
    if profile:
        exact = [p for p in candidates if p.get("accountName") == profile]
        if len(exact) == 1: return exact[0]
    raise CollectionError("account_requires_binding")


def token_reading(binding, raw):
    limits = raw.get("limits") or {}
    provider = match_account(binding, limits.get("providers", []))
    if provider.get("status") != "ok": raise CollectionError("provider_unavailable")
    observed = instant(provider.get("updatedAt"))
    windows = []
    for index, window in enumerate(provider.get("windows", [])):
        windows.append(Window(id=str(window.get("limitId") or f"{window.get('kind','quota')}:{index}"),
            label=window.get("label") or window.get("kind") or "Quota",
            unit=window.get("currency") or window.get("unit"), used=window.get("used"),
            limit=window.get("limit"), remaining=window.get("remaining"), used_percent=window.get("usedPercent"),
            resets_at=window.get("resetsAt"), observed_at=observed))
    refresh = limits.get("refreshMs") or 0
    lifetime = min(86400, max(900, int(refresh / 500)))
    return Reading(windows=windows, observed_at=observed, stale=bool(provider.get("stale")), valid_for_seconds=lifetime)


def network_reading(binding, raw):
    row = next((r for r in raw["items"] if r["id"] == binding["account"]), None)
    if row is None: raise CollectionError("account_requires_binding")
    info = row.get("userinfo") or {}
    observed = instant(row.get("observed_at"))
    upload, download, total = (info.get(k) for k in ("upload", "download", "total"))
    used = upload + download if upload is not None and download is not None else None
    remaining = max(0, total-used) if total is not None and used is not None else None
    windows = []
    if total is not None or used is not None:
        windows.append(Window(id="traffic", label="供应商流量", unit="bytes", used=used, limit=total,
            remaining=remaining, used_percent=min(100, used/total*100) if used is not None and total else None,
            observed_at=observed))
    for key, value in (("upload", upload), ("download", download)):
        if value is not None:
            windows.append(Window(id=key, label="供应商上传" if key == "upload" else "供应商下载", unit="bytes", used=value, observed_at=observed))
    expiry = datetime.fromtimestamp(info["expire"], timezone.utc) if info.get("expire") else None
    return Reading(windows=windows, observed_at=observed, expires_at=expiry,
                   stale=bool(row.get("stale")), valid_for_seconds=row.get("valid_for_seconds", 900))


def quota_reading(url, config):
    try:
        row = fetch_userinfo(url, trusted_base=(config.get('subboost') or {}).get('url'))
        return network_reading({'account': 'subscription_url'}, {'items': [row]})
    except QuotaError as exc:
        raise CollectionError(str(exc)) from None
    except (ValueError, TypeError, OverflowError, OSError):
        raise CollectionError('invalid_quota_header') from None


def collect(store, config):
    lock_path = Path(store.database + ".collect.lock")
    with lock_path.open("a") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return {"skipped": True, "reason": "already_running"}
        payloads, errors = {}, {}
        with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
            for source, path in (("token_monitor", "/api/stats"), ("subboost", "/api/integrations/subscriptions")):
                settings = config.get(source) or {}
                if not settings.get("url") or not settings.get("token"):
                    errors[source] = "unconfigured"
                    continue
                try:
                    response = client.get(settings["url"].rstrip("/")+path, headers={"Authorization": "Bearer "+settings["token"]})
                    response.raise_for_status()
                    raw = response.json()
                    catalog = []
                    if source == "token_monitor":
                        for p in (raw.get("limits") or {}).get("providers", []):
                            if p.get("accountKey"):
                                catalog.append({"collector": source, "provider": p["provider"], "account": p["accountKey"],
                                    "account_email": p.get("accountEmail") or "", "profile": p.get("accountName") or "",
                                    "status": p.get("status"), "observed_at": p.get("updatedAt")})
                    else:
                        catalog = [{"collector": source, "provider": "network", "account": r["id"], "profile": r["name"],
                                    "observed_at": r.get("observed_at")} for r in raw["items"]]
                    payloads[source] = raw
                    store.catalog(source, catalog)
                except httpx.HTTPStatusError as error:
                    errors[source] = "authentication" if error.response.status_code in (401, 403) else "source_http_error"
                except httpx.TimeoutException: errors[source] = "timeout"
                except httpx.RequestError: errors[source] = "connection"
                except (ValueError, KeyError, TypeError): errors[source] = "invalid_payload"
        summary = {"updated": 0, "failed": 0, "sources": {s: errors.get(s, "ok") for s in ("token_monitor", "subboost")}}
        summary["exchange_rates"] = refresh(store)
        offset = 0
        direct = {}
        while True:
            page = store.list(offset, 200, include_private=True)
            for item in page["items"]:
                binding = item["binding"]
                quota_url = item['quota_url']
                if not item["active"] or not (binding or quota_url): continue
                if quota_url:
                    if quota_url not in direct:
                        try: direct[quota_url] = (quota_reading(quota_url, config), None)
                        except CollectionError as exc: direct[quota_url] = (None, str(exc))
                    reading, error = direct[quota_url]
                    if store.observe(item['id'], binding, reading, error, quota_url=quota_url):
                        summary['failed' if error else 'updated'] += 1
                    continue
                reading, error = None, errors.get(binding["collector"])
                if error is None:
                    try:
                        raw = payloads[binding["collector"]]
                        reading = (token_reading if binding["collector"] == "token_monitor" else network_reading)(binding, raw)
                    except CollectionError as exc: error = str(exc)
                    except (ValueError, KeyError, TypeError, OverflowError): error = "invalid_payload"
                if store.observe(item["id"], binding, reading, error): summary["failed" if error else "updated"] += 1
            if page["next_offset"] is None: break
            offset = page["next_offset"]
        return summary
