"""Native source payloads become business records; no raw payload is stored."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .models import Bill, HealthDay, SLEEP_STAGES, business_day, instant, merge_health, utc

BILL_TYPES = dict(zip(
    ("Expend", "ExpendReimbursement", "ExpendLending", "ExpendRepayment", "Income", "IncomeLending", "IncomeRepayment", "IncomeReimbursement", "IncomeRefund", "Transfer"),
    ("expense", "expense_reimbursement", "expense_lending", "expense_repayment", "income", "income_lending", "income_repayment", "income_reimbursement", "income_refund", "transfer"),
))


def provenance(item):
    metadata = item.get("metadata") or {}
    return {target: metadata[source] for source, target in (("data_origin", "origin"), ("device", "device")) if metadata.get(source) is not None}


def health(payload: Any) -> dict[str, dict]:
    if not isinstance(payload, dict):
        raise ValueError("health body must be an object")
    days = defaultdict(dict)
    for source, target, field in (("steps", "steps", "count"), ("active_calories", "active_calories_kcal", "calories"), ("total_calories", "total_calories_kcal", "calories")):
        values = payload.get(source, [])
        if isinstance(values, (int, float)) and not isinstance(values, bool):
            values = [{field: values, "start_time": payload.get("timestamp"), "end_time": payload.get("timestamp")}]
        if not isinstance(values, list):
            raise ValueError(f"{source} must be an array")
        for sample in sorted(values, key=lambda s: utc(s.get("end_time", s.get("start_time")))):
            stamp = sample.get("start_time", sample.get("end_time"))
            days[business_day(stamp)][target] = sample[field]
    for name, value_field in (("heart_rate", "bpm"), ("resting_heart_rate", "bpm"), ("oxygen_saturation", "percentage"), ("basal_metabolic_rate", "watts")):
        values = payload.get(name, [])
        if not isinstance(values, list):
            raise ValueError(f"{name} must be an array")
        for sample in values:
            stamp = utc(sample["time"])
            days[business_day(stamp)].setdefault(name, []).append({"time": stamp, value_field: sample[value_field], **provenance(sample)})
    for session in payload.get("sleep", []):
        end = utc(session["session_end_time"])
        selected = days[business_day(end)].setdefault("sleep", [])
        stages = session.get("stages") or []
        if stages:
            for stage in stages:
                number = stage["stage"]
                name = SLEEP_STAGES.get(int(number)) if isinstance(number, (int, str)) and str(number).isdigit() else number
                selected.append({"start": utc(stage["start_time"]), "end": utc(stage["end_time"]), "stage": name, **provenance(session)})
        else:
            start = utc(instant(end) - timedelta(seconds=float(session["duration_seconds"])))
            selected.append({"start": start, "end": end, "stage": "unknown", **provenance(session)})
    for session in payload.get("exercise", []):
        end = utc(session["end_time"])
        start = utc(session["start_time"]) if session.get("start_time") else utc(instant(end) - timedelta(seconds=float(session["duration_seconds"])))
        item = {"start": start, "end": end, "type": str(session.get("type", "unknown")), **provenance(session)}
        item.update({key: session[key] for key in ("steps", "avg_cadence_spm") if session.get(key) is not None})
        days[business_day(end)].setdefault("exercise", []).append(item)
    return {d: merge_health({}, HealthDay(date=d, **data).data()) for d, data in days.items()}


def bill(payload: Any) -> Bill:
    if not isinstance(payload, dict):
        raise ValueError("bill body must be an object")
    native_id, stamp = payload.get("id"), payload.get("time")
    if isinstance(native_id, bool) or not isinstance(native_id, int) or native_id <= 0:
        raise ValueError("bill id must be a positive integer")
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp <= 0:
        raise ValueError("bill time must be epoch milliseconds")
    if payload.get("state") not in ("Synced", "Edited", "Wait2Edit"):
        raise ValueError("unknown bill state")
    if payload.get("type") not in BILL_TYPES:
        raise ValueError("unknown bill type")
    currency = payload.get("currency")
    if isinstance(currency, str) and currency.lstrip().startswith("{"):
        currency = json.loads(currency)["code"]
    tags = payload.get("tags") or []
    if isinstance(tags, str):
        tags = json.loads(tags) if tags.lstrip().startswith("[") else [tags]
    fields = {target: payload[source] for source, target in (
        ("bookName", "book"), ("cateName", "category"), ("accountNameFrom", "account_from"),
        ("accountNameTo", "account_to"), ("shopName", "merchant"), ("shopItem", "item"), ("remark", "note"),
    ) if payload.get(source) is not None}
    return Bill(id=str(uuid5(NAMESPACE_URL, f"personal-records:autoaccounting:{native_id}")),
        source="autoaccounting", source_id=str(native_id),
        occurred_at=utc(datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=stamp)),
        type=BILL_TYPES[payload["type"]], amount=payload["money"], currency=currency,
        fee=payload.get("fee", "0"), status="pending" if payload["state"] == "Wait2Edit" else "confirmed", tags=tags, **fields)
