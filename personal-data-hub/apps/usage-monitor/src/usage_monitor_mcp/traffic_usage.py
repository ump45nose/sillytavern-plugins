from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .time_window import instant


DIMENSIONS = {"categories": "category", "pools": "pool", "nodes": "exit_node", "sources": "source_tag"}


def _overlap(start, end, window):
    start, end = max(start, window.start), min(end, window.end)
    return (start, end) if end > start else None


def _union_seconds(intervals):
    total = 0
    previous = None
    for start, end in sorted(intervals):
        if previous is None:
            previous = [start, end]
        elif start <= previous[1]:
            previous[1] = max(previous[1], end)
        else:
            total += (previous[1] - previous[0]).total_seconds()
            previous = [start, end]
    if previous:
        total += (previous[1] - previous[0]).total_seconds()
    return total


def read_traffic(settings, window):
    connection = None
    try:
        zone = ZoneInfo(settings.traffic_timezone)
        local_start = window.start.astimezone(zone)
        local_end = window.end.astimezone(zone)
        # Existing fact rows have local hourly bucket keys, without offsets.
        # A midnight boundary must match the collector's hourly grid.
        if local_start.minute or local_start.second or window.start.utcoffset() != local_start.utcoffset():
            return {"status": "unavailable", "error": "collector_day_boundary_differs", "totals": None,
                    "source_timezone": settings.traffic_timezone}
        connection = sqlite3.connect(settings.traffic_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        start_key = local_start.strftime("%Y-%m-%dT%H:%M")
        end_key = local_end.strftime("%Y-%m-%dT%H:%M:%S.%f")
        # Exact end at an hourly boundary excludes the next hour.
        if local_end.minute == local_end.second == local_end.microsecond == 0:
            end_key = local_end.strftime("%Y-%m-%dT%H:%M")
        params = (start_key, end_key)
        where = "bucket >= ? AND bucket < ?"
        total = connection.execute(
            "SELECT SUM(upload_bytes), SUM(download_bytes), COUNT(*), MIN(bucket), MAX(bucket) "
            "FROM traffic_hourly WHERE " + where, params).fetchone()
        dimensions = {}
        for name, column in DIMENSIONS.items():
            dimensions[name] = [
                {"name": name_value, "upload_bytes": up, "download_bytes": down, "total_bytes": up + down}
                for name_value, up, down in connection.execute(
                    f"SELECT {column}, SUM(upload_bytes), SUM(download_bytes) FROM traffic_hourly WHERE {where} "
                    f"GROUP BY {column} ORDER BY SUM(upload_bytes + download_bytes) DESC, {column}", params)
            ]
        hours = [r[0] for r in connection.execute(
            "SELECT DISTINCT bucket FROM traffic_hourly WHERE " + where + " ORDER BY bucket", params)]
        last_row = connection.execute("SELECT value FROM collector_meta WHERE key='last_sample'").fetchone()
        last_sample = instant(last_row[0]) if last_row else None
        first_bucket = connection.execute("SELECT MIN(bucket) FROM traffic_hourly").fetchone()[0]
        earliest = datetime.fromisoformat(first_bucket).replace(tzinfo=zone) if first_bucket else None
        gaps, intervals = [], []
        for start_text, end_text, reason in connection.execute("SELECT started_at, ended_at, reason FROM collector_gaps"):
            start = instant(start_text)
            end = instant(end_text) if end_text else window.end
            if start is None or end is None:
                continue
            interval = _overlap(start, end, window)
            if interval:
                intervals.append(interval)
                gaps.append({"start": interval[0].isoformat(), "end": interval[1].isoformat(),
                             "reason": str(reason)[:120], "open": end_text is None})
        if last_sample is None:
            intervals.append((window.start, window.end))
        elif last_sample < window.end - timedelta(seconds=10):
            interval = _overlap(last_sample, window.end, window)
            if interval:
                intervals.append(interval)
                gaps.append({"start": interval[0].isoformat(), "end": interval[1].isoformat(),
                             "reason": "collector has not reported through requested end", "open": True})
        if earliest and earliest > window.start:
            interval = _overlap(window.start, earliest, window)
            if interval:
                intervals.append(interval)
                gaps.append({"start": interval[0].isoformat(), "end": interval[1].isoformat(),
                             "reason": "before earliest retained bucket", "open": False})
        missing_hours = []
        cursor = local_start
        while cursor < local_end:
            key = cursor.strftime("%Y-%m-%dT%H:%M")
            if key not in hours:
                missing_hours.append(key)
            cursor += timedelta(hours=1)
        seconds = max(0, (window.end - window.start).total_seconds())
        gap_seconds = min(seconds, _union_seconds(intervals))
        available = total[2] > 0
        return {
            "status": "partial" if gaps and available else "ok" if available else "unavailable",
            "source": "shellcrash-traffic/traffic.sqlite3",
            "source_timezone": settings.traffic_timezone,
            "totals": {"upload_bytes": total[0], "download_bytes": total[1],
                       "total_bytes": total[0] + total[1] if available else None,
                       "aggregate_rows": total[2]},
            "dimensions": dimensions,
            "coverage": {
                "first_traffic_bucket": total[3], "last_traffic_bucket": total[4],
                "last_sample": last_sample.isoformat() if last_sample else None,
                "sample_interval_seconds": 1, "fact_resolution": "hour",
                "window_seconds": round(seconds, 3), "known_gap_seconds": round(gap_seconds, 3),
                "recorded_gap_count": len(gaps), "gaps": gaps,
                "hours_with_traffic": len(hours), "hours_without_traffic_rows": missing_hours,
                "exact_sample_coverage_percent": None,
            },
            "coverage_note": "每秒采样、按小时存增量；未持久化每次成功采样，无法声称精确采样覆盖率。无流量行的小时可能没有流量，也可能未采集。短于采样间隔的连接可能漏记。",
            "aggregation_basis": "只汇总一次事实表字节数；策略组、节点、流量池、订阅源是独立分类维度，不能相加。策略组类别保留采集器原标签，不推断具体访问内容。",
        }
    except (OSError, sqlite3.Error, ValueError, KeyError) as error:
        return {"status": "unavailable", "source": "shellcrash-traffic/traffic.sqlite3",
                "error": type(error).__name__, "totals": None, "dimensions": {}}
    finally:
        if connection is not None:
            connection.close()
