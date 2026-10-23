"""个人复盘系统的稳定领域对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EvidenceKind(StrEnum):
    """允许进入候选池的状态变化类型。"""

    DELIVERY = "delivery"
    DECISION = "decision"
    BLOCKER = "blocker"
    EXTERNAL_FEEDBACK = "external_feedback"
    RELATIONSHIP = "relationship"
    HEALTH_CHANGE = "health_change"
    FINANCE_CHANGE = "finance_change"
    GIT_ACTIVITY = "git_activity"
    ROUTINE = "routine"


class ReviewKind(StrEnum):
    """支持的人工确认复盘类型。"""

    DAILY = "daily"
    WEEKLY = "weekly"
    STAGE = "stage"
    ANNUAL = "annual"


@dataclass(frozen=True)
class TimeWindow:
    """使用半开区间表达一次证据采集窗口。"""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """确保窗口带时区且起点早于终点。"""

        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("TimeWindow 必须使用带时区时间")
        if self.start >= self.end:
            raise ValueError("TimeWindow 起点必须早于终点")


@dataclass(frozen=True)
class Evidence:
    """保存可追溯但尚未被用户确认的候选事实。"""

    evidence_id: str
    source: str
    kind: EvidenceKind
    occurred_at: datetime
    fact: str
    subject: str = ""
    source_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReviewSession:
    """保存一次被冻结的复盘材料包及其生命周期。"""

    session_id: str
    kind: ReviewKind
    window: TimeWindow
    status: str
    evidence: list[Evidence]
    prepared_at: datetime
    expires_at: datetime
    final_content: str | None = None
    memo_name: str | None = None
