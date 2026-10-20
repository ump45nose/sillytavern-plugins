#!/usr/bin/env python3
"""Emit one alert per Health freshness incident and one recovery message.

An unhealthy data source is a successful inspection result, not a failure of
the cron runner itself.  The process therefore exits non-zero only when the
checker crashes before it can record the inspection result.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from health_data import health_rows


def _parse_time(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("received_at has no timezone")
    return parsed


def _load_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".health-freshness-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o660)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def inspect(db_path: Path, now: datetime, max_age_hours: float) -> tuple[str, str, str]:
    try:
        rows = health_rows(db_path, latest=True)
        row = rows[-1][1:] if rows else None
    except Exception as exc:
        return "unhealthy", "source_unreadable", type(exc).__name__
    if row is None:
        return "unhealthy", "no_payload", "health_payloads is empty"
    received_at, payload_json = row
    try:
        json.loads(payload_json)
    except Exception as exc:
        return "unhealthy", "invalid_json", type(exc).__name__
    try:
        received = _parse_time(str(received_at))
        age_hours = (now.astimezone(received.tzinfo) - received).total_seconds() / 3600
    except Exception as exc:
        return "unhealthy", "invalid_timestamp", type(exc).__name__
    if age_hours > max_age_hours:
        return "unhealthy", "stale", f"latest={received.isoformat()} age={age_hours:.1f}h"
    return "healthy", "fresh", f"latest={received.isoformat()} age={age_hours:.1f}h"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("/home/hermes/.local/share/health.db"))
    parser.add_argument(
        "--state",
        type=Path,
        default=Path("/home/hermes/.hermes/profiles/lingjun/tmp/health-freshness-state.json"),
    )
    parser.add_argument("--max-age-hours", type=float, default=3.0)
    parser.add_argument("--now", default="")
    args = parser.parse_args()
    now = _parse_time(args.now) if args.now else datetime.now().astimezone()
    status, reason, detail = inspect(args.db, now, args.max_age_hours)
    previous = _load_state(args.state).get("status")
    _save_state(
        args.state,
        {"status": status, "reason": reason, "detail": detail, "checked_at": now.isoformat()},
    )
    if status == "unhealthy" and previous != "unhealthy":
        print(f"Health 数据告警：{reason}（{detail}）")
    elif status == "healthy" and previous == "unhealthy":
        print(f"Health 数据已恢复：{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
