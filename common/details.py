"""Bounded delivery facts only; never accept an upstream response object."""

import math
import re
from urllib.parse import urlsplit

UNITS = {"points", "coins", "beans", "days", "count"}
STATES = {"complete", "incomplete", "unknown", "not_applicable", "blocked"}
NUMBERS = {"current", "max", "before", "after", "delta"}


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
    except (ValueError, TypeError):
        return None
    return n if math.isfinite(n) and abs(n) <= 1e12 else None


def metric(unit, current=None, maximum=None, before=None, after=None, delta=None):
    return {"unit": unit, "current": number(current), "max": number(maximum),
            "before": number(before), "after": number(after), "delta": number(delta)}


def validate_details(value):
    if not isinstance(value, dict) or set(value) != {"metrics", "items"}:
        raise ValueError("invalid_details")
    metrics, items = value["metrics"], value["items"]
    if not isinstance(metrics, dict) or len(metrics) > 32:
        raise ValueError("invalid_metrics")
    for key, row in metrics.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                or not isinstance(row, dict) or set(row) != NUMBERS | {"unit"}
                or row["unit"] not in UNITS):
            raise ValueError("invalid_metric")
        for field in NUMBERS:
            n = row[field]
            if n is not None and (type(n) not in (int, float) or number(n) is None
                                  or (field != "delta" and n < 0)):
                raise ValueError("invalid_metric_number")
    if not isinstance(items, list) or len(items) > 100:
        raise ValueError("invalid_items")
    for row in items:
        if (not isinstance(row, dict) or set(row) - {"id", "name", "url", "status", "reason"}
                or not {"id", "name", "status", "reason"} <= set(row)
                or row["status"] not in STATES):
            raise ValueError("invalid_item")
        for field, limit in (("id", 128), ("name", 200), ("reason", 100)):
            text = row[field]
            if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 for c in text):
                raise ValueError("invalid_item_text")
        if not re.fullmatch(r"[a-z0-9_]{1,100}", row["reason"]):
            raise ValueError("invalid_item_reason")
        if "url" in row:
            u = urlsplit(row["url"])
            if (not isinstance(row["url"], str) or len(row["url"]) > 512
                    or u.scheme != "https" or not u.hostname or u.username or u.password
                    or u.query or u.fragment or u.port not in (None, 443)):
                raise ValueError("invalid_item_url")
    return value
