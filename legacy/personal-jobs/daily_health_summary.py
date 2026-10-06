#!/usr/bin/env python3
"""Read-only health.db summary for the daily-review cron."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

DB_PATH = Path("/home/hermes/.local/share/health.db")
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def parse_time(value: object) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL_TZ)
    except ValueError:
        return None


def main() -> int:
    try:
        hours = max(1, min(int(sys.argv[1]) if len(sys.argv) > 1 else 24, 168))
    except ValueError:
        print("hours 必须是整数", file=sys.stderr)
        return 2

    if not DB_PATH.is_file():
        print("健康数据不可用：数据库不存在")
        return 1

    now = datetime.now(LOCAL_TZ)
    window_start = now - timedelta(hours=hours)
    fetch_start = window_start - timedelta(hours=6)

    connection = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT id, received_at, payload_json "
            "FROM health_payloads ORDER BY id ASC"
        ).fetchall()
    finally:
        connection.close()

    payloads: list[tuple[int, datetime, dict]] = []
    invalid_payloads = 0
    for payload_id, received_at, payload_json in rows:
        received = parse_time(received_at)
        if received is None or received < fetch_start:
            continue
        try:
            body = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            invalid_payloads += 1
            continue
        if isinstance(body, dict):
            payloads.append((payload_id, received, body))

    if not payloads:
        print(f"近 {hours} 小时没有可用健康同步数据。")
        print(
            "SUMMARY_JSON="
            + json.dumps(
                {"ok": True, "hours": hours, "payloads": 0},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    steps_by_day: dict[str, int] = {}
    sleep_by_end: dict[str, int] = {}
    heart_rate: dict[tuple[str, int], int] = {}
    resting: tuple[datetime, int] | None = None

    for _payload_id, received, body in payloads:
        for item in body.get("steps") or []:
            if not isinstance(item, dict) or item.get("count") is None:
                continue
            end = parse_time(item.get("end_time"))
            start = parse_time(item.get("start_time"))
            if end is not None and end < window_start:
                continue
            day = (start or end or received).strftime("%Y-%m-%d")
            count = int(item["count"])
            steps_by_day[day] = max(steps_by_day.get(day, 0), count)

        for item in body.get("sleep") or []:
            if not isinstance(item, dict):
                continue
            end = parse_time(item.get("session_end_time"))
            duration = int(item.get("duration_seconds") or 0)
            if end is None or end < window_start - timedelta(hours=12):
                continue
            key = end.isoformat()
            sleep_by_end[key] = max(sleep_by_end.get(key, 0), duration)

        for item in body.get("heart_rate") or []:
            if not isinstance(item, dict) or item.get("bpm") is None:
                continue
            sample_time = parse_time(item.get("time"))
            if sample_time is None or not window_start <= sample_time <= now:
                continue
            bpm = int(item["bpm"])
            heart_rate[(sample_time.isoformat(), bpm)] = bpm

        for item in body.get("resting_heart_rate") or []:
            if not isinstance(item, dict) or item.get("bpm") is None:
                continue
            sample_time = parse_time(item.get("time"))
            if sample_time is None or sample_time < window_start - timedelta(hours=12):
                continue
            candidate = (sample_time, int(item["bpm"]))
            if resting is None or candidate[0] > resting[0]:
                resting = candidate

    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    steps = steps_by_day.get(today)
    if steps is None:
        steps = steps_by_day.get(yesterday)

    longest_sleep_segment = max(sleep_by_end.values(), default=0) // 60
    rates = list(heart_rate.values())
    parts: list[str] = []
    if steps is not None:
        parts.append(f"今日步数累计 {steps}")
    if longest_sleep_segment:
        parts.append(f"最长睡眠片段 {longest_sleep_segment} 分钟")
    if rates:
        average = round(sum(rates) / len(rates))
        parts.append(f"心率均值 {average} bpm（{min(rates)}–{max(rates)}）")
    if resting is not None:
        parts.append(f"静息心率 {resting[1]} bpm")

    sync_count = sum(1 for _pid, received, _body in payloads if received >= window_start)
    latest_sync = max(received for _pid, received, _body in payloads)
    if parts:
        print("；".join(parts[:4]) + "。")
    else:
        print(f"近 {hours} 小时收到 {sync_count} 份健康同步，但没有可汇总指标。")

    summary = {
        "ok": True,
        "hours": hours,
        "payloads": sync_count,
        "invalid_payloads": invalid_payloads,
        "latest_sync": latest_sync.isoformat(),
        "steps": steps,
        "longest_sleep_segment_minutes": longest_sleep_segment or None,
        "heart_rate_samples": len(rates),
        "heart_rate_average": round(sum(rates) / len(rates), 1) if rates else None,
        "resting_heart_rate": resting[1] if resting else None,
        "note": "cumulative daily metrics use max snapshot; repeated samples are deduplicated",
    }
    print("SUMMARY_JSON=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
