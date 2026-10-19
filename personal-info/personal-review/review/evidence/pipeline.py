"""把多来源原始候选压缩成可供用户确认的事实列表。"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import re
from typing import Iterable

from review.domain import Evidence, EvidenceKind


def _compact(text: str) -> str:
    """统一空白和标点，以便跨来源比较同一事实。"""

    return re.sub(r"\s+", " ", text).strip(" -\t\r\n")


def stable_evidence_id(source: str, occurred_at: str, fact: str) -> str:
    """生成不会因执行顺序变化而改变的短证据编号。"""

    raw = f"{source}\0{occurred_at}\0{_compact(fact).lower()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


class EvidencePipeline:
    """执行显式准入、日志排除和保守跨来源去重。"""

    def __init__(self, policy: dict) -> None:
        """从 YAML 策略读取允许类型、排除词和时间窗口。"""

        admitted = policy["evidence"]["admitted_kinds"]
        self.admitted = {EvidenceKind(value) for value in admitted}
        self.excluded = [re.compile(re.escape(value), re.IGNORECASE) for value in policy["evidence"]["excluded_patterns"]]
        self.window = timedelta(minutes=int(policy["evidence"]["dedupe_window_minutes"]))
        self.source_priority = {
            name: index for index, name in enumerate(policy["sources"]["priority"])
        }

    def normalize(self, item: Evidence) -> Evidence:
        """清理事实文本，但保留来源和原始结构化负载。"""

        return Evidence(
            evidence_id=item.evidence_id,
            source=item.source,
            kind=item.kind,
            occurred_at=item.occurred_at,
            fact=_compact(item.fact),
            subject=_compact(item.subject),
            source_ref=item.source_ref,
            payload=item.payload,
        )

    def admit(self, item: Evidence) -> bool:
        """只接收状态变化，明确排除 Hermes 自身运行痕迹。"""

        if item.kind not in self.admitted or not item.fact:
            return False
        return not any(pattern.search(item.fact) for pattern in self.excluded)

    def process(self, items: Iterable[Evidence]) -> list[Evidence]:
        """标准化并以主体、事实词和时间接近度去重。"""

        normalized = [self.normalize(item) for item in items]
        admitted = [item for item in normalized if self.admit(item)]
        admitted.sort(
            key=lambda item: (
                item.occurred_at,
                -self.source_priority.get(item.source, 999),
            )
        )

        result: list[Evidence] = []
        for item in admitted:
            duplicate_index = self._find_duplicate(result, item)
            if duplicate_index is None:
                result.append(item)
                continue
            existing = result[duplicate_index]
            if self.source_priority.get(item.source, 999) < self.source_priority.get(existing.source, 999):
                result[duplicate_index] = item
        return sorted(result, key=lambda item: item.occurred_at)

    def _find_duplicate(self, existing: list[Evidence], candidate: Evidence) -> int | None:
        """寻找同主体或高度相似事实的近时间候选。"""

        candidate_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", candidate.fact.lower()))
        for index, item in enumerate(existing):
            # Skysight 的每个文件对应独立时间窗；通用近似去重不能吞掉相邻窗口。
            if item.source == candidate.source == "skysight" and item.source_ref != candidate.source_ref:
                continue
            if abs(candidate.occurred_at - item.occurred_at) > self.window:
                continue
            if candidate.subject and candidate.subject == item.subject:
                return index
            item_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", item.fact.lower()))
            union = candidate_tokens | item_tokens
            if union and len(candidate_tokens & item_tokens) / len(union) >= 0.72:
                return index
        return None
