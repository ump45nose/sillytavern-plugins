"""消费 no-agent 生成的 Google Calendar 与 Tasks 当日摘要。"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor


class _GoogleBriefSource:
    """实现 Google 摘要文件的公共解析和游标行为。"""

    source_name = "google"
    item_key = "items"

    def __init__(self, directory: str | Path) -> None:
        """记录每日 Google 摘要目录。"""

        self.directory = Path(directory)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """读取业务日摘要，只返回窗口内最小结构化事实。"""

        day = window.end.astimezone(window.start.tzinfo).date().isoformat()
        path = self.directory / f"{day}.json"
        if not path.is_file():
            return SourceResult(self.source_name, warnings=[f"{self.source_name} 摘要未就绪"])
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return SourceResult(self.source_name, warnings=[f"{self.source_name} 摘要无法解析"])

        items = payload.get(self.item_key, []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return SourceResult(self.source_name, warnings=[f"{self.source_name} 摘要结构不兼容"])
        evidence: list[Evidence] = []
        for item in items:
            parsed = self._evidence(item, window)
            if parsed is None or not is_after_cursor(parsed.occurred_at, parsed.source_ref, checkpoint):
                continue
            evidence.append(parsed)
        errors = payload.get("errors", []) if isinstance(payload, dict) else []
        warnings = [str(value)[:160] for value in errors if str(value).startswith(f"{self.source_name}:")]
        return SourceResult(self.source_name, evidence, warnings, encode_cursor(evidence))

    def _evidence(self, item: Any, window: TimeWindow) -> Evidence | None:
        """由子类把一个安全摘要项转换为 Evidence。"""

        raise NotImplementedError

    @staticmethod
    def _time(value: Any, window: TimeWindow) -> datetime | None:
        """解析带时区 ISO 时间，并验证其落入日报窗口。"""

        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=window.start.tzinfo)
        except ValueError:
            return None
        local = parsed.astimezone(window.start.tzinfo)
        return parsed if window.start <= local < window.end else None


class GoogleCalendarBriefSource(_GoogleBriefSource):
    """读取当日未取消日历事件，不消费 description 等正文。"""

    source_name = "google_calendar"
    item_key = "calendar"

    def _evidence(self, item: Any, window: TimeWindow) -> Evidence | None:
        """把一个最小 Calendar 事件转换为候选。"""

        if not isinstance(item, dict) or str(item.get("status")) == "cancelled":
            return None
        title = str(item.get("summary") or "").strip()
        occurred = self._time(item.get("occurred_at"), window)
        event_id = str(item.get("id") or "").strip()
        if not title or occurred is None or not event_id:
            return None
        period = str(item.get("period") or "").strip()
        fact = f"日历：{title}" + (f"（{period}）" if period else "")
        source_ref = f"calendar:{event_id}"
        return Evidence(
            stable_evidence_id("google_calendar", occurred.isoformat(), source_ref),
            "google_calendar",
            EvidenceKind.DELIVERY,
            occurred,
            fact,
            subject=title,
            source_ref=source_ref,
        )


class GoogleTasksBriefSource(_GoogleBriefSource):
    """只读取当天真实完成的 Google Tasks。"""

    source_name = "google_tasks"
    item_key = "tasks"

    def __init__(self, directory: str | Path, policy: dict) -> None:
        """记录摘要目录和任务标题浓缩上限。"""

        super().__init__(directory)
        self.max_titles = int(policy["sources"]["aggregation"]["google_tasks_max_titles"])

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """读取完成事件并把同日任务浓缩为一个候选。"""

        result = super().collect(window, checkpoint)
        if len(result.evidence) <= 1:
            return result
        ordered = sorted(result.evidence, key=lambda item: (item.occurred_at, item.source_ref))
        titles = list(dict.fromkeys(item.subject for item in ordered if item.subject))
        shown = titles[: self.max_titles]
        omitted = max(0, len(titles) - len(shown))
        details = "；".join(shown)
        if omitted:
            details += f"；另 {omitted} 项已折叠"
        fact = f"Google Tasks：当天完成 {len(ordered)} 项"
        if details:
            fact += f"（{details}）"
        latest = ordered[-1]
        summary = Evidence(
            stable_evidence_id("google_tasks", latest.occurred_at.isoformat(), fact),
            "google_tasks",
            EvidenceKind.DELIVERY,
            latest.occurred_at,
            fact,
            subject="Google Tasks 当日完成",
            source_ref=f"tasks-summary:{latest.source_ref}",
            payload={"titles": shown, "omitted_count": omitted},
        )
        return SourceResult(self.source_name, [summary], result.warnings, encode_cursor([summary]))

    def _evidence(self, item: Any, window: TimeWindow) -> Evidence | None:
        """把一个已完成 Task 转换为候选。"""

        if not isinstance(item, dict) or str(item.get("status")) != "completed":
            return None
        title = str(item.get("title") or "").strip()
        occurred = self._time(item.get("completed_at"), window)
        task_id = str(item.get("id") or "").strip()
        list_id = str(item.get("tasklist_id") or "").strip()
        if not title or occurred is None or not task_id or not list_id:
            return None
        source_ref = f"tasks:{list_id}:{task_id}"
        return Evidence(
            stable_evidence_id("google_tasks", occurred.isoformat(), source_ref),
            "google_tasks",
            EvidenceKind.DELIVERY,
            occurred,
            f"Google Task 已完成：{title}",
            subject=title,
            source_ref=source_ref,
            payload={"titles": [title]},
        )
