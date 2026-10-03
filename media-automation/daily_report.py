#!/usr/bin/env python3
"""Read MoviePilot and Emby Theme worker SQLite data and print a daily report."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Taipei")
MOVIEPILOT_DB = Path("/vol2/1000/Docker/moviepilot/config/user.db")
THEME_WORKER_DB = Path("/vol2/1000/Docker/emby-theme-worker/data/worker.db")


def parse_time(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), TIMEZONE)
        else:
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=TIMEZONE)
            else:
                parsed = parsed.astimezone(TIMEZONE)
        return parsed
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def open_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def moviepilot_rows() -> tuple[list[dict], list[dict]]:
    with closing(open_readonly(MOVIEPILOT_DB)) as connection:
        downloads = [
            dict(row) for row in connection.execute(
                "SELECT title, torrent_name, date, download_hash, username "
                "FROM downloadhistory"
            )
        ]
        plugin_rows = connection.execute(
            "SELECT value FROM plugindata "
            "WHERE plugin_id = ? AND key = ?",
            ("FilmWatchlist", "records"),
        ).fetchall()

    records: list[dict] = []
    for row in plugin_rows:
        try:
            payload = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("FilmWatchlist records JSON is invalid") from exc
        if isinstance(payload, dict):
            if "title" in payload or "status" in payload:
                candidates = [payload]
            else:
                candidates = list(payload.values())
        elif isinstance(payload, list):
            candidates = payload
        else:
            candidates = []
        records.extend(dict(item) for item in candidates if isinstance(item, dict))
    return downloads, records


def theme_worker_rows() -> list[dict]:
    with closing(open_readonly(THEME_WORKER_DB)) as connection:
        return [
            dict(row) for row in connection.execute(
                "SELECT name, status, source_provider, updated_at FROM items"
            )
        ]


def wrapped_title(value: object) -> str:
    title = str(value or "").strip()
    if title.startswith("《") and title.endswith("》"):
        return title
    return f"《{title or '未命名影视'}》"


def display_time(value: datetime | None) -> str:
    return value.strftime("%m-%d %H:%M") if value else "时间未知"


def recent_rows(
    rows: list[dict], time_field: str, cutoff: datetime
) -> tuple[list[dict], int]:
    recent: list[dict] = []
    invalid = 0
    for row in rows:
        value = row.get(time_field)
        parsed = parse_time(value)
        if parsed is None:
            raw_date = str(value or "").strip()[:10]
            if raw_date >= cutoff.date().isoformat():
                invalid += 1
            continue
        if parsed >= cutoff:
            row["_parsed_time"] = parsed
            recent.append(row)
    return recent, invalid


def watchlist_records(records: list[dict]) -> dict[str, dict]:
    by_hash: dict[str, dict] = {}
    for record in records:
        key = str(record.get("download_hash") or "").strip()
        if not key:
            continue
        current = by_hash.get(key)
        updated = parse_time(record.get("updated_at"))
        previous = parse_time(current.get("updated_at")) if current else None
        if current is None or (updated and (previous is None or updated > previous)):
            by_hash[key] = record
    return by_hash


def build_report(now: datetime) -> tuple[str, int]:
    cutoff = now - timedelta(hours=24)
    downloads, records = moviepilot_rows()
    theme_items = theme_worker_rows()
    recent_downloads, invalid_downloads = recent_rows(downloads, "date", cutoff)
    recent_records, invalid_records = recent_rows(records, "updated_at", cutoff)
    recent_theme, invalid_theme = recent_rows(theme_items, "updated_at", cutoff)
    status_by_hash = watchlist_records(records)

    lines = [f"影视自动化日报 {now:%Y-%m-%d %H:%M}（过去24小时）"]
    lines.append(f"下载提交（{len(recent_downloads)}）")
    linked_hashes: set[str] = set()
    for row in sorted(recent_downloads, key=lambda item: item["_parsed_time"]):
        title = wrapped_title(row.get("title"))
        source = str(row.get("username") or "来源未知").strip()
        download_hash = str(row.get("download_hash") or "").strip()
        record = status_by_hash.get(download_hash) if source == "FilmWatchlist" else None
        lines.append(f"- {title}：提交时间 {display_time(row['_parsed_time'])}；来源 {source}")
        if source == "FilmWatchlist":
            if record is not None:
                linked_hashes.add(download_hash)
                status = str(record.get("status") or "状态未知").strip()
                lines.append(f"  片单处理状态：{status}")
            else:
                lines.append("  片单处理状态：未找到匹配记录")
        release = str(row.get("torrent_name") or "").strip()
        if release:
            lines.append(f"  下载格式：{release}")

    independent_records = [
        row for row in recent_records
        if str(row.get("download_hash") or "").strip() not in linked_hashes
    ]
    lines.append(f"片单状态更新（{len(independent_records)}）")
    for row in sorted(independent_records, key=lambda item: item["_parsed_time"]):
        status = str(row.get("status") or "状态未知").strip()
        lines.append(
            f"- {wrapped_title(row.get('title'))}：片单处理状态 {status}；"
            f"更新时间 {display_time(row['_parsed_time'])}"
        )
        release = str(row.get("torrent_title") or "").strip()
        if release:
            lines.append(f"  下载格式：{release}")

    lines.append(f"主题曲任务（{len(recent_theme)}）")
    for row in sorted(recent_theme, key=lambda item: item["_parsed_time"]):
        status = str(row.get("status") or "状态未知").strip()
        provider = str(row.get("source_provider") or "来源未知").strip()
        lines.append(
            f"- {wrapped_title(row.get('name'))}：{status}；来源 {provider}；"
            f"更新时间 {display_time(row['_parsed_time'])}"
        )

    invalid = invalid_downloads + invalid_records + invalid_theme
    if invalid:
        lines.append(f"数据提示：{invalid} 条记录的时间字段无法解析，报告可能不完整。")
    if not recent_downloads and not independent_records and not recent_theme and not invalid:
        lines.append("过去24小时无新增下载、片单状态更新或主题曲处理记录。")
    return "\n".join(lines), invalid


def main() -> int:
    now = datetime.now(TIMEZONE)
    try:
        report, _invalid = build_report(now)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(
            f"影视自动化日报失败：只读数据库查询异常"
            f"（{type(exc).__name__}: {str(exc).splitlines()[0][:220]}）"
        )
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
