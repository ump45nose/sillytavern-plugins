"""Small, strict result protocol. Unknown is never completion."""

import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from .details import validate_details

MAX_RESULT = 65536
STATUSES = {"complete", "incomplete", "unknown", "not_applicable", "blocked"}
EXECUTIONS = {"ok", "failed", "timeout", "busy"}


def result(context, execution="failed", reason="unknown", business=None, details=None):
    return {
        "schema_version": 1,
        **{k: context[k] for k in ("run_id", "platform", "account", "business_date")},
        "execution_status": execution,
        "reason": reason,
        "business": business or {"checkin": "unknown", "reward": "unknown"},
        "details": validate_details(details or {"metrics": {}, "items": []}),
    }


def validate(value, context):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("invalid_schema")
    for key in ("run_id", "platform", "account", "business_date"):
        if value.get(key) != context[key]:
            raise ValueError("result_identity_mismatch")
    if value.get("execution_status") not in EXECUTIONS:
        raise ValueError("invalid_execution_status")
    if not isinstance(value.get("reason"), str) or len(value["reason"]) > 256:
        raise ValueError("invalid_reason")
    business = value.get("business")
    if not isinstance(business, dict) or not business or len(business) > 32:
        raise ValueError("invalid_business")
    if any(
        not isinstance(k, str) or len(k) > 64 or v not in STATUSES
        for k, v in business.items()
    ):
        raise ValueError("invalid_business_status")
    # Adapters may not inject arbitrary account responses or credentials.
    allowed = {
        "schema_version",
        "run_id",
        "platform",
        "account",
        "business_date",
        "execution_status",
        "reason",
        "business",
        "details", "started_at", "finished_at", "duration_ms",
    }
    if set(value) - allowed:
        raise ValueError("unexpected_result_fields")
    if "details" in value:
        validate_details(value["details"])
    for key in ("started_at", "finished_at"):
        if key in value and (not isinstance(value[key], str) or
                             datetime.fromisoformat(value[key]).tzinfo is None):
            raise ValueError("invalid_result_time")
    if "duration_ms" in value and (type(value["duration_ms"]) is not int or
                                    not 0 <= value["duration_ms"] <= 1e12):
        raise ValueError("invalid_result_duration")
    return dict(value)


def read_result(path, context):
    with open(path, "rb") as stream:
        raw = stream.read(MAX_RESULT + 1)
    if len(raw) > MAX_RESULT:
        raise ValueError("result_too_large")
    return validate(json.loads(raw), context)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    if len(payload) > MAX_RESULT:
        raise ValueError("result_too_large")
    fd, tmp = tempfile.mkstemp(prefix=".result-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def progress(current, maximum, eligibility=None):
    if eligibility == "not_applicable":
        return "not_applicable"
    if eligibility == "blocked":
        return "blocked"
    if (
        isinstance(current, bool)
        or isinstance(maximum, bool)
        or current is None
        or maximum is None
    ):
        return "unknown"
    try:
        current, maximum = float(current), float(maximum)
    except (TypeError, ValueError):
        return "unknown"
    if (
        not math.isfinite(current)
        or not math.isfinite(maximum)
        or current < 0
        or maximum <= 0
    ):
        return "unknown"
    return "complete" if current >= maximum else "incomplete"
