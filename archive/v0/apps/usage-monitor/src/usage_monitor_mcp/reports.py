from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .time_window import Window
from .token_usage import read_tokens
from .traffic_usage import read_traffic


def build_report(settings, day=None, now: datetime | None = None):
    window = Window.make(day, settings.timezone, now)
    return {
        "schema_version": 1, "report_id": "usage-" + window.day.isoformat(),
        "window": window.metadata(),
        "token_monitor": read_tokens(settings, window),
        "shellcrash": read_traffic(settings, window),
    }


def summary(report, top=10):
    token, network = report["token_monitor"], report["shellcrash"]
    coverage = network.get("coverage", {})
    result = {
        "report_id": report["report_id"], "window": report["window"],
        "token_monitor": {k: token.get(k) for k in
                          ("status", "totals", "coverage", "cost_basis", "aggregation_basis", "stats_api_status")},
        "shellcrash": {k: network.get(k) for k in ("status", "totals", "source_timezone", "coverage_note")},
    }
    result["token_monitor"].update(
        top_models=token.get("models", [])[:top], top_tools=token.get("tools", [])[:top],
        devices=token.get("devices", [])[:50],
        subscriptions_status=token.get("subscriptions", {}).get("status", "unavailable"),
        actual_paid_today=None,
    )
    result["shellcrash"]["coverage"] = {k: coverage.get(k) for k in
        ("last_sample", "known_gap_seconds", "recorded_gap_count", "hours_with_traffic", "exact_sample_coverage_percent")}
    result["shellcrash"]["top_dimensions"] = {k: v[:top] for k, v in network.get("dimensions", {}).items()}
    return result


@contextmanager
def file_lock(path):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def atomic_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ReportStore:
    def __init__(self, data_dir):
        self.directory = Path(data_dir) / "reports"

    def _path(self, report_id):
        if not isinstance(report_id, str) or not re.fullmatch(r"usage-\d{4}-\d{2}-\d{2}", report_id):
            raise ValueError("报告 ID 无效")
        return self.directory / (report_id + ".json")

    def get(self, report_id):
        path = self._path(report_id)
        if not path.is_file():
            return None
        with path.open() as handle:
            return json.load(handle)

    def save_once(self, report):
        path = self._path(report["report_id"])
        with file_lock(self.directory / ".archive.lock"):
            existing = self.get(report["report_id"])
            if existing is not None:
                return existing
            atomic_json(path, report)
        return report

    def list(self, offset=0, limit=30):
        _page(offset, limit)
        paths = sorted(self.directory.glob("usage-????-??-??.json"), reverse=True)
        rows = []
        for path in paths[offset:offset + limit]:
            item = self.get(path.stem)
            rows.append({"report_id": item["report_id"], "window": item["window"],
                         "token_status": item["token_monitor"]["status"],
                         "network_status": item["shellcrash"]["status"]})
        return {"reports": rows, "offset": offset, "total": len(paths),
                "next_offset": offset + limit if offset + limit < len(paths) else None}


def _page(offset, limit):
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("offset 必须非负，limit 范围为 1—100")


SECTIONS = {
    "token_models": ("token_monitor", "models"),
    "token_tools": ("token_monitor", "tools"),
    "token_devices": ("token_monitor", "devices"),
    "token_limits": ("token_monitor", "limits_snapshot"),
    "subscription_records": ("token_monitor", "subscriptions", "records"),
    "network_categories": ("shellcrash", "dimensions", "categories"),
    "network_pools": ("shellcrash", "dimensions", "pools"),
    "network_nodes": ("shellcrash", "dimensions", "nodes"),
    "network_sources": ("shellcrash", "dimensions", "sources"),
    "network_gaps": ("shellcrash", "coverage", "gaps"),
}


def report_page(report, section="summary", offset=0, limit=50):
    _page(offset, limit)
    if section == "summary":
        result = summary(report)
        result["available_sections"] = list(SECTIONS)
        return result
    if section not in SECTIONS:
        raise ValueError("报告 section 无效")
    rows = report
    for key in SECTIONS[section]:
        rows = rows.get(key, {}) if isinstance(rows, dict) else {}
    if not isinstance(rows, list):
        rows = []
    return {"report_id": report["report_id"], "section": section, "rows": rows[offset:offset + limit],
            "offset": offset, "total": len(rows), "next_offset": offset + limit if offset + limit < len(rows) else None}
