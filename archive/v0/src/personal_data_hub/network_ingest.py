"""Fixed SSH ingestion boundary for a Mac's proxy-accounting facts."""
from datetime import datetime
import json
import re
from zoneinfo import ZoneInfo

from sqlalchemy import select
from .contracts import Batch, Record, digest, instant, utcnow
from .storage import records

DIMENSIONS = ("bucket", "destination_ip", "host", "process", "source_ip", "category", "pool", "source_tag", "exit_node", "rule")


def ingest_network(store, payload):
    device = payload.get("device_id", "")
    if not isinstance(device, str) or not re.fullmatch(r"[a-f0-9]{32}", device): raise ValueError("invalid_network_device")
    zone = payload.get("timezone", ""); tz = ZoneInfo(zone)
    batch_id = payload.get("batch_id")
    if batch_id != digest({k: v for k, v in payload.items() if k != "batch_id"}): raise ValueError("invalid_network_batch_hash")
    incoming = payload.get("records")
    if not isinstance(incoming, list) or not 1 <= len(incoming) <= 250: raise ValueError("invalid_network_batch_size")
    source = "network-mac-" + device
    items = []
    for row in incoming:
        raw = row["raw"]; kind = row["kind"]; eid = row["external_id"]
        if not isinstance(raw, dict): raise ValueError("invalid_network_record")
        normal = {"table": kind, "device_id": device, "collector_id": "clash", "measurement_scope": "proxy", "measurement_point": "endpoint"}
        occurred = None
        if kind == "traffic_hourly":
            if set(raw) != set(DIMENSIONS) | {"upload_bytes", "download_bytes"}: raise ValueError("invalid_network_dimensions")
            if any(not isinstance(raw[k], str) or len(raw[k]) > 2048 for k in DIMENSIONS): raise ValueError("invalid_network_dimension")
            if any(type(raw[k]) is not int or not 0 <= raw[k] <= 2**63 - 1 for k in ("upload_bytes", "download_bytes")): raise ValueError("invalid_network_counter")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:00", raw["bucket"]): raise ValueError("invalid_network_hour")
            occurred = datetime.fromisoformat(raw["bucket"]).replace(tzinfo=tz)
            if eid != "hour:" + digest({k: raw[k] for k in DIMENSIONS}): raise ValueError("invalid_network_hour_identity")
            normal.update(upload_bytes=raw["upload_bytes"], download_bytes=raw["download_bytes"], grain="hour+destination+process+route", cumulative=True)
        elif kind == "collector_gaps":
            if set(raw) != {"id", "started_at", "ended_at", "reason"} or type(raw["id"]) is not int or raw["id"] <= 0 or eid != "gap:" + str(raw["id"]): raise ValueError("invalid_network_gap")
            occurred = instant(raw["started_at"])
            if occurred is None or (raw["ended_at"] is not None and instant(raw["ended_at"]) < occurred): raise ValueError("invalid_network_gap_window")
            if not isinstance(raw["reason"], str) or len(raw["reason"]) > 120: raise ValueError("invalid_network_gap_reason")
        elif kind == "collector_meta":
            if set(raw) != {"key", "value"} or raw["key"] != "last_sample" or eid != "meta:last_sample": raise ValueError("invalid_network_metadata")
            occurred = instant(raw["value"])
            if occurred is None: raise ValueError("invalid_network_sample_time")
        else: raise ValueError("invalid_network_kind")
        items.append(Record(eid, kind, raw, normal, occurred, timezone=zone))
    store.register(source, "owner", "shellcrash", "explicit_only")
    with store.lock("source:" + source):
        with store.engine.begin() as connection:
            for item in items:
                old = connection.execute(select(records.c.raw).where(records.c.id == store.identity(source, item.external_id))).scalar()
                if old and item.kind == "traffic_hourly":
                    # A delayed retry cannot reduce an already committed cumulative fact.
                    for key in ("upload_bytes", "download_bytes"):
                        item.raw[key] = max(item.raw[key], old[key]); item.normalized[key] = item.raw[key]
            result = store.ingest(source, Batch(items), connection=connection)
    return {"batch_id": batch_id, "source": source, "accepted": len(items), "committed": True, **result}
