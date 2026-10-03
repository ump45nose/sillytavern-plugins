"""Collect and commit source batches without consuming the download queue."""
import logging
import time

from .common import SyncError
from .config import start_timestamp
from .sources import ScanResult

log = logging.getLogger("favsync")


def collect_source(cfg, store, guard, spec, section, adapter):
    """Return scan success, or None when the source has no download phase."""
    source, account = spec.name, section["account"]
    state = store.source(source, account)
    if hasattr(adapter, "sync_metadata"):
        store.update(source, account, scan_status="scanning", error=None)
        adapter.sync_metadata(store, source, account)
        return None
    configured_date = (section.get("start_date", "") if spec.date_section == source else
                       cfg[spec.date_section].get("start_date", "")) if spec.date_section else ""
    start = start_timestamp(configured_date, cfg["timezone"]) if spec.date_section else None
    if source == "telegram_notice":
        start = float(store.setting("markdown_v2_since"))
    if spec.date_section and (start is None or (spec.adapter == "pixiv" and time.time() < start)):
        store.update(source, account, scan_status="awaiting_start_date", error=None)
        return None
    baseline = spec.baseline and state["baseline_at"] is None
    store.update(source, account, scan_status="initializing_baseline" if baseline else "scanning", error=None)
    cursor = state["cursor"] if state["start_date"] == str(configured_date) else 0
    result = ScanResult.coerce(adapter.scan(source, cursor=cursor, start=start))
    if baseline and not result.complete:
        raise SyncError("scan_incomplete")
    guard.validate_scan(spec, account, adapter)
    records, bad_dates = result.records, 0
    if source == "x_bookmarks":
        bad_dates = sum(r["action_time"] is None for r in records)
        records = [r for r in records if r["action_time"] is not None and r["action_time"] >= start]
    if spec.adapter == "wallabag":
        store.ingest_wallabag(source, account, records)
        store.update(source, account, scan_reason=result.reason,
                     scan_status="complete" if result.complete else "partial")
    else:
        store.apply_scan(source, account, result, records=records,
                         baseline=baseline, start_date=str(configured_date))
    if bad_dates:
        store.update(source, account, scan_status="incomplete", error="bookmark_time_unknown")
    log.info("%s: %s, records=%d reason=%s", source,
             "baseline_complete" if baseline else ("scan_complete" if result.complete else "scan_partial"),
             len(records), result.reason)
    return not bad_dates
