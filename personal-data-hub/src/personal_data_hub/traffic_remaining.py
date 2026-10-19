"""Lightweight reader for subscription remaining traffic facts."""
from datetime import datetime, timezone
import os
import re
import urllib.request

DEFAULT_SUBSCRIPTION_URL = "https://us17.dbxzs.com:7677/clash/ewomxzdnypreokt9"


def parse_userinfo_header(header_value: str) -> dict:
    """Parse Clash Subscription-Userinfo header into numeric values."""
    facts = {}
    for part in header_value.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        try:
            facts[key] = int(value.strip())
        except ValueError:
            continue
    total = facts.get("total", 0)
    upload = facts.get("upload", 0)
    download = facts.get("download", 0)
    expire = facts.get("expire")
    used = upload + download
    remaining = max(0, total - used)

    expires_at = None
    if expire and expire > 0:
        expires_at = datetime.fromtimestamp(expire, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "total_bytes": total,
        "upload_bytes": upload,
        "download_bytes": download,
        "used_bytes": used,
        "remaining_bytes": remaining,
        "total_gb": round(total / (1024 ** 3), 2),
        "used_gb": round(used / (1024 ** 3), 2),
        "remaining_gb": round(remaining / (1024 ** 3), 2),
        "usage_percent": round((used / total) * 100, 1) if total > 0 else 0.0,
        "expires_at": expires_at,
        "checked_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
    }


def fetch_remaining_traffic(url: str | None = None, timeout: float = 10.0) -> dict:
    """Fetch and parse subscription remaining traffic info from HTTP headers."""
    target_url = url or os.environ.get("TRAFFIC_SUBSCRIPTION_URL", DEFAULT_SUBSCRIPTION_URL)
    req = urllib.request.Request(target_url, headers={"User-Agent": "ClashMeta"}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
    except Exception:
        # Fallback to GET with small byte range if HEAD is rejected
        req = urllib.request.Request(target_url, headers={"User-Agent": "ClashMeta", "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}

    userinfo = headers.get("subscription-userinfo")
    if not userinfo:
        raise ValueError(f"No Subscription-Userinfo header returned from {target_url}")

    data = parse_userinfo_header(userinfo)
    data["url"] = target_url
    return data
