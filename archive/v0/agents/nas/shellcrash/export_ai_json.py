#!/usr/bin/env python3
"""Export a compact rolling ShellCrash traffic snapshot for AI analysis."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path


DEFAULT_DB = "/var/lib/shellcrash-traffic/traffic.sqlite3"
DEFAULT_OUT = "/var/lib/shellcrash-traffic/ai-summary.json"

DIMENSIONS = {
    "categories": "category",
    "pools": "pool",
    "sources": "source_tag",
    "nodes": "exit_node",
    "hosts": "host",
    "processes": "process",
    "source_ips": "source_ip",
    "rules": "rule",
}


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def dimension_rows(
    conn: sqlite3.Connection,
    column: str,
    start_bucket: str,
    top: int,
) -> list[dict]:
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF({column}, ''), 'unknown'),
               SUM(upload_bytes),
               SUM(download_bytes),
               SUM(upload_bytes + download_bytes)
        FROM traffic_hourly
        WHERE bucket >= ?
        GROUP BY {column}
        ORDER BY SUM(upload_bytes + download_bytes) DESC
        LIMIT ?
        """,
        (start_bucket, top),
    ).fetchall()
    return [
        {
            "key": key,
            "upload_bytes": int(upload or 0),
            "download_bytes": int(download or 0),
            "total_bytes": int(total or 0),
        }
        for key, upload, download, total in rows
    ]


def daily_rows(conn: sqlite3.Connection, start_bucket: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT substr(bucket, 1, 10),
               SUM(upload_bytes),
               SUM(download_bytes),
               SUM(upload_bytes + download_bytes)
        FROM traffic_hourly
        WHERE bucket >= ?
        GROUP BY substr(bucket, 1, 10)
        ORDER BY 1
        """,
        (start_bucket,),
    ).fetchall()
    return [
        {
            "date": date,
            "upload_bytes": int(upload or 0),
            "download_bytes": int(download or 0),
            "total_bytes": int(total or 0),
        }
        for date, upload, download, total in rows
    ]
def build_snapshot(db_path: str, days: int, top: int) -> dict:
    generated = now()
    start = generated - dt.timedelta(days=days)
    start_bucket = start.strftime("%Y-%m-%dT%H:00")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    totals = conn.execute(
        """
        SELECT SUM(upload_bytes),
               SUM(download_bytes),
               SUM(upload_bytes + download_bytes),
               COUNT(*)
        FROM traffic_hourly
        WHERE bucket >= ?
        """,
        (start_bucket,),
    ).fetchone()
    coverage = conn.execute(
        """
        SELECT MIN(bucket), MAX(bucket)
        FROM traffic_hourly
        WHERE bucket >= ?
        """,
        (start_bucket,),
    ).fetchone()
    meta = dict(conn.execute("SELECT key, value FROM collector_meta").fetchall())
    gaps = [
        {
            "started_at": started,
            "ended_at": ended or "OPEN",
            "reason": reason,
        }
        for started, ended, reason in conn.execute(
            """
            SELECT started_at, ended_at, reason
            FROM collector_gaps
            WHERE started_at >= ?
            ORDER BY started_at
            """,
            (start.isoformat(timespec="seconds"),),
        ).fetchall()
    ]

    snapshot = {
        "schema_version": 1,
        "generated_at": generated.isoformat(timespec="seconds"),
        "window": {
            "days": days,
            "requested_start": start.isoformat(timespec="seconds"),
            "coverage_start": coverage[0],
            "coverage_end": coverage[1],
        },
        "totals": {
            "upload_bytes": int(totals[0] or 0),
            "download_bytes": int(totals[1] or 0),
            "total_bytes": int(totals[2] or 0),
            "aggregate_rows": int(totals[3] or 0),
        },
        "daily": daily_rows(conn, start_bucket),
        "dimensions": {
            name: dimension_rows(conn, column, start_bucket, top)
            for name, column in DIMENSIONS.items()
        },
        "collector": {
            "meta": meta,
            "gap_count": len(gaps),
            "gaps": gaps,
        },
    }
    conn.close()
    return snapshot


def write_atomic(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".partial")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    staging.replace(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--top", type=int, default=100)
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be >= 1")
    if args.top < 1:
        parser.error("--top must be >= 1")

    write_atomic(args.out, build_snapshot(args.db, args.days, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
