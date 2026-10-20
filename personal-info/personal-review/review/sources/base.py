"""证据来源的通用接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from review.domain import Evidence, TimeWindow


@dataclass
class SourceResult:
    """返回一个来源的候选事实和非阻断告警。"""

    source: str
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_checkpoint: str | None = None


class SourceAdapter(Protocol):
    """所有来源都必须实现相同的增量采集签名。"""

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """读取窗口内事实，但不得在成功前推进 checkpoint。"""

        ...

