"""以只读方式消费设备健康快照并生成结构化摘要。"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from statistics import mean
from typing import Any, Iterable

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor


METRIC_KEYS = {
    "steps": ("count", 1.0),
    "sleep": ("duration_seconds", 1 / 3600),
    "heart_rate": ("bpm", 1.0),
    "resting_heart_rate": ("bpm", 1.0),
    "oxygen_saturation": ("percentage", 1.0),
    "active_calories": ("calories", 1.0),
    "total_calories": ("calories", 1.0),
    "exercise": ("duration_seconds", 1 / 60),
}

METRIC_TIME_KEYS = {
    "steps": ("end_time", "start_time"),
    "sleep": ("session_end_time",),
    "heart_rate": ("time",),
    "resting_heart_rate": ("time",),
    "oxygen_saturation": ("time",),
    "active_calories": ("end_time", "start_time"),
    "total_calories": ("end_time", "start_time"),
    "exercise": ("end_time", "start_time"),
}


def _metric_numbers(metric: str, value: Any) -> list[float]:
    """按设备字段契约提取数值，避免把 metadata 中数字误当指标。"""

    if isinstance(value, bool) or value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list):
        values: list[float] = []
        for item in value:
            if isinstance(item, dict):
                key, factor = METRIC_KEYS.get(metric, ("value", 1.0))
                raw = item.get(key)
                if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    values.append(float(raw) * factor)
            else:
                values.extend(_metric_numbers(metric, item))
        return values
    if isinstance(value, dict):
        key, factor = METRIC_KEYS.get(metric, ("value", 1.0))
        raw = value.get(key)
        return [float(raw) * factor] if isinstance(raw, (int, float)) and not isinstance(raw, bool) else []
    return []


class HealthSource:
    """读取健康 SQLite 的时间窗快照，不透传原始 payload。"""

    def __init__(self, database: str | Path, metrics: Iterable[str]) -> None:
        """记录只读数据库位置和允许输出的指标白名单。"""

        self.database = Path(database)
        self.metrics = tuple(metrics)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """聚合窗口内快照；坏 JSON 和错误字段只形成警告。"""

        if not self.database.is_file():
            return SourceResult("health", warnings=["健康数据库不存在"])
        uri = f"file:{self.database}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            rows = connection.execute(
                "SELECT received_at,payload_json FROM health_payloads "
                "WHERE julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?) "
                "ORDER BY julianday(received_at)",
                (window.start.isoformat(), window.end.isoformat()),
            ).fetchall()
        finally:
            connection.close()

        warnings: list[str] = []
        snapshots: list[tuple[datetime, dict[str, Any]]] = []
        for received_at, raw_payload in rows:
            try:
                payload = json.loads(raw_payload)
                if not isinstance(payload, dict):
                    raise TypeError("顶层不是对象")
                timestamp = datetime.fromisoformat(received_at)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=window.start.tzinfo)
                source_ref = f"health.db@{timestamp.isoformat()}"
                if not is_after_cursor(timestamp, source_ref, checkpoint):
                    continue
                snapshots.append((timestamp, payload))
            except (ValueError, TypeError, json.JSONDecodeError):
                warnings.append("存在无法解析的健康快照")
        if not snapshots:
            return SourceResult("health", warnings=sorted(set(warnings + ["窗口内没有健康数据"])))

        weekly = window.end - window.start > timedelta(days=2)
        summary = self._weekly_summary(snapshots, window) if weekly else self._daily_summary(snapshots, window)
        freshness = self._freshness(snapshots, window)
        summary["freshness"] = freshness
        stale_metrics = sorted(
            metric for metric, value in freshness.items()
            if value.get("last_event_date") != window.start.date().isoformat()
        )
        if not weekly and stale_metrics:
            warnings.append("健康指标事件滞后：" + "、".join(stale_metrics))

        occurred_at = snapshots[-1][0]
        readable = self._format_weekly_summary(summary) if weekly else self._format_summary(summary)
        evidence = Evidence(
            stable_evidence_id("health", occurred_at.isoformat(), readable),
            "health",
            EvidenceKind.HEALTH_CHANGE,
            occurred_at,
            readable,
            subject="健康",
            source_ref=f"health.db@{occurred_at.isoformat()}",
            payload=summary,
        )
        return SourceResult("health", [evidence], sorted(set(warnings)), encode_cursor([evidence]))

    def _freshness(
        self,
        snapshots: list[tuple[datetime, dict[str, Any]]],
        window: TimeWindow,
    ) -> dict[str, dict[str, Any]]:
        """记录每项指标最近事件日期和接收延迟，不保存指标原始值。"""

        result: dict[str, dict[str, Any]] = {}
        for metric in self.metrics:
            latest_event: datetime | None = None
            latest_received: datetime | None = None
            for received_at, payload in snapshots:
                for occurred_at, _, _ in self._metric_records(metric, payload.get(metric), received_at):
                    if latest_event is None or occurred_at > latest_event:
                        latest_event = occurred_at
                        latest_received = received_at
            if latest_event is None or latest_received is None:
                continue
            event_local = latest_event.astimezone(window.start.tzinfo)
            received_local = latest_received.astimezone(window.start.tzinfo)
            result[metric] = {
                "last_event_date": event_local.date().isoformat(),
                "receive_lag_hours": round(max(0.0, (received_local - event_local).total_seconds() / 3600), 1),
            }
        return result

    def _daily_summary(
        self,
        snapshots: list[tuple[datetime, dict[str, Any]]],
        window: TimeWindow,
    ) -> dict[str, Any]:
        """按指标自身事件时间汇总当日记录，补传和重复记录不重复计数。"""

        summary: dict[str, Any] = {"coverage_snapshots": len(snapshots)}
        for metric in self.metrics:
            by_day = self._metric_values_by_day(metric, snapshots, window)
            values = [value for day_values in by_day.values() for value in day_values]
            aggregated = self._aggregate_metric(metric, values)
            if aggregated is not None:
                summary[metric] = aggregated
        return summary

    def _weekly_summary(
        self,
        snapshots: list[tuple[datetime, dict[str, Any]]],
        window: TimeWindow,
    ) -> dict[str, Any]:
        """按本地日期选择最完整指标快照，再计算覆盖天数、日均和首末变化。"""

        span_days = max(1, (window.end.date() - window.start.date()).days + 1)
        summary: dict[str, Any] = {"window_days": span_days, "snapshot_days": 0}
        covered_days: set[str] = set()
        for metric in self.metrics:
            values_by_day = self._metric_values_by_day(metric, snapshots, window)
            daily_values: list[tuple[str, float]] = []
            for day, values in sorted(values_by_day.items()):
                aggregated = self._aggregate_metric(metric, values)
                if aggregated is not None:
                    daily_values.append((day, float(aggregated)))
                    covered_days.add(day)
            if not daily_values:
                continue
            values = [value for _, value in daily_values]
            summary[metric] = {
                "coverage_days": len(values),
                "average": round(mean(values), 1),
                "change": round(values[-1] - values[0], 1) if len(values) >= 2 else None,
            }
        summary["snapshot_days"] = len(covered_days)
        return summary

    def _metric_values_by_day(
        self,
        metric: str,
        snapshots: list[tuple[datetime, dict[str, Any]]],
        window: TimeWindow,
    ) -> dict[str, list[float]]:
        """按事件时间切日，并以时间区间键去掉跨快照重复记录。"""

        records: dict[tuple[str, str], tuple[datetime, float]] = {}
        for received_at, payload in snapshots:
            for occurred_at, record_key, value in self._metric_records(metric, payload.get(metric), received_at):
                local = occurred_at.astimezone(window.start.tzinfo)
                if not (window.start <= local < window.end):
                    continue
                day = local.date().isoformat()
                key = (day, record_key)
                previous = records.get(key)
                cumulative = metric in {"steps", "sleep", "active_calories", "total_calories", "exercise"}
                if previous is None or (cumulative and value > previous[1]) or (not cumulative and received_at >= previous[0]):
                    records[key] = (received_at, value)
        by_day: dict[str, list[float]] = {}
        for (day, _), (_, value) in records.items():
            by_day.setdefault(day, []).append(value)
        return by_day

    @staticmethod
    def _metric_records(
        metric: str,
        raw_value: Any,
        received_at: datetime,
    ) -> list[tuple[datetime, str, float]]:
        """从一个 payload 提取事件时刻、稳定区间键和规范化数值。"""

        items = raw_value if isinstance(raw_value, list) else [raw_value]
        records: list[tuple[datetime, str, float]] = []
        for index, item in enumerate(items):
            values = _metric_numbers(metric, item)
            if not values:
                continue
            occurred_at = received_at
            identity_parts: list[str] = []
            if isinstance(item, dict):
                for key in METRIC_TIME_KEYS.get(metric, ()):
                    raw_time = item.get(key)
                    if raw_time is None:
                        continue
                    text = str(raw_time)
                    identity_parts.append(f"{key}={text}")
                    if occurred_at == received_at:
                        try:
                            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                            occurred_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=received_at.tzinfo)
                        except ValueError:
                            pass
            # 没有事件时间的单值消息用接收时刻和数组位置区分，避免把真实测量误合并。
            identity = "|".join(identity_parts) or f"received={received_at.isoformat()}|index={index}"
            for value_index, value in enumerate(values):
                records.append((occurred_at, f"{identity}|value-index={value_index}", value))
        return records

    @staticmethod
    def _aggregate_metric(metric: str, values: list[float]) -> float | int | None:
        """按设备指标语义聚合一次累计快照。"""

        if not values:
            return None
        if metric in {"steps", "active_calories", "total_calories"}:
            return round(max(values))
        if metric == "sleep":
            return round(max(values), 1)
        if metric == "exercise":
            return round(sum(values), 1)
        return round(mean(values), 1)

    @staticmethod
    def _format_summary(summary: dict[str, Any]) -> str:
        """把白名单指标渲染为紧凑中文，不为缺失项补零。"""

        labels = {
            "steps": "步数",
            "sleep": "睡眠",
            "resting_heart_rate": "静息心率",
            "heart_rate": "平均心率",
            "oxygen_saturation": "血氧",
            "active_calories": "活动热量",
            "total_calories": "总热量",
            "exercise": "运动",
        }
        units = {
            "steps": "步",
            "sleep": "小时",
            "resting_heart_rate": "次/分",
            "heart_rate": "次/分",
            "oxygen_saturation": "%",
            "active_calories": "千卡",
            "total_calories": "千卡",
            "exercise": "分钟",
        }
        parts = [f"{labels[key]} {value}{units[key]}" for key, value in summary.items() if key in labels]
        return "；".join(parts) if parts else "窗口内有健康快照，但无可用指标"

    @staticmethod
    def _format_weekly_summary(summary: dict[str, Any]) -> str:
        """输出真实覆盖天数和首末变化，不把缺失日当成零。"""

        labels = {
            "steps": "步数", "sleep": "睡眠", "resting_heart_rate": "静息心率",
            "heart_rate": "平均心率", "oxygen_saturation": "血氧", "active_calories": "活动热量",
            "total_calories": "总热量", "exercise": "运动",
        }
        units = {
            "steps": "步", "sleep": "小时", "resting_heart_rate": "次/分", "heart_rate": "次/分",
            "oxygen_saturation": "%", "active_calories": "千卡", "total_calories": "千卡", "exercise": "分钟",
        }
        span = int(summary.get("window_days", 0))
        parts = [f"设备覆盖 {int(summary.get('snapshot_days', 0))}/{span} 天"]
        for metric in labels:
            value = summary.get(metric)
            if not isinstance(value, dict):
                continue
            change = value.get("change")
            trend = "" if change is None else f"，首末 {float(change):+g}{units[metric]}"
            parts.append(
                f"{labels[metric]} {value['coverage_days']}/{span} 天，日均 {value['average']:g}{units[metric]}{trend}"
            )
        return "；".join(parts)
