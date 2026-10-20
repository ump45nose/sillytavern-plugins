"""把 Google Tasks 完成状态作为待确认候选，不直接修改账本。"""

from __future__ import annotations

from datetime import datetime

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor
from review.state import StateRepository


class TaskCompletionSource:
    """读取由真实 Tasks 回执记录的完成事件。"""

    def __init__(self, state: StateRepository) -> None:
        """绑定运行状态库。"""

        self.state = state

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """只生成候选事实；用户未引用时不会进入任何 Memos。"""

        with self.state.connect() as connection:
            rows = connection.execute(
                "SELECT event_key,external_id,title,status,occurred_at FROM task_events "
                "WHERE julianday(occurred_at)>=julianday(?) AND julianday(occurred_at)<julianday(?) "
                "AND status='completed' ORDER BY julianday(occurred_at),event_key",
                (window.start.isoformat(), window.end.isoformat()),
            ).fetchall()
        evidence: list[Evidence] = []
        for row in rows:
            occurred = datetime.fromisoformat(row["occurred_at"])
            source_ref = str(row["event_key"])
            if not is_after_cursor(occurred, source_ref, checkpoint):
                continue
            fact = f"Google Task 已标记完成：{row['title']}"
            evidence.append(
                Evidence(
                    stable_evidence_id("google_tasks", occurred.isoformat(), source_ref),
                    "google_tasks",
                    EvidenceKind.DELIVERY,
                    occurred,
                    fact,
                    subject=str(row["external_id"]),
                    source_ref=source_ref,
                )
            )
        return SourceResult("google_tasks", evidence, [], encode_cursor(evidence))
