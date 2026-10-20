"""把已确认 Memos 作为高优先级历史事实来源。"""

from __future__ import annotations

from datetime import datetime
import re

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.ledger import MemosClient, MemosError
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor


class MemosSource:
    """读取确认账本中的近期变化，不把旧内容重新解释成人格判断。"""

    def __init__(self, client: MemosClient, excluded_tags: list[str] | tuple[str, ...] | None = None) -> None:
        """绑定 Memos 客户端，并记录不应回灌日报材料的系统账本标签。"""

        self.client = client
        self.excluded_tags = {tag.strip().lstrip("#") for tag in (excluded_tags or ()) if tag.strip()}

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """按更新时间筛选窗口内 Memo，并生成有限确认事实。"""

        try:
            memos = self.client.list_memos(page_size=100)
        except MemosError as exc:
            return SourceResult("memos", warnings=[str(exc)])
        evidence: list[Evidence] = []
        for memo in memos:
            timestamp = self._time(memo)
            if timestamp is None:
                continue
            local = timestamp.astimezone(window.start.tzinfo)
            if not (window.start <= local < window.end):
                continue
            content = str(memo.get("content", "")).strip()
            if not content:
                continue
            tags = self._tags(memo, content)
            if not tags:
                continue
            # 日报、主线和阶段目标已有专用读取路径，不能再作为普通 Memos 候选重复展示。
            if tags & self.excluded_tags:
                continue
            fact = self._summary(content)
            kind = EvidenceKind.DECISION if "决定" in content else EvidenceKind.DELIVERY
            name = str(memo.get("name", memo.get("id", "")))
            if not is_after_cursor(timestamp, name, checkpoint):
                continue
            evidence.append(
                Evidence(
                    stable_evidence_id("memos", timestamp.isoformat(), fact),
                    "memos",
                    kind,
                    timestamp,
                    fact,
                    subject=name,
                    source_ref=name,
                    payload={"tags": sorted(tags), "memo_markdown": content},
                )
            )
        return SourceResult("memos", evidence, [], encode_cursor(evidence))

    @staticmethod
    def _time(memo: dict) -> datetime | None:
        """兼容 Memos 常见时间字段。"""

        for key in ("updateTime", "updatedTs", "createTime", "createdTs"):
            value = memo.get(key)
            if isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return parsed if parsed.tzinfo else parsed.astimezone()
                except ValueError:
                    continue
            if isinstance(value, (int, float)):
                return datetime.fromtimestamp(value).astimezone()
        return None

    @staticmethod
    def _summary(content: str) -> str:
        """取首个非标签事实行，避免把整篇终稿回灌成候选。"""

        for line in content.splitlines():
            text = line.strip()
            if text and not re.fullmatch(r"#\S+(?:\s+\S+)?", text):
                return text[:240]
        return content.replace("\n", " ")[:240]

    @staticmethod
    def _tags(memo: dict, content: str) -> set[str]:
        """合并 Memos 结构化标签与正文 hashtag；只有完全无标签的 Memo 才会被过滤。"""

        tags: set[str] = set()
        for key in ("tags", "tagNames", "tag_names"):
            values = memo.get(key)
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str) and value.strip():
                        tags.add(value.strip().lstrip("#"))
                    elif isinstance(value, dict):
                        name = str(value.get("name") or value.get("tag") or "").strip()
                        if name:
                            tags.add(name.lstrip("#"))
        # 结构化标签和正文 hashtag 都属于用户显式标注，不再套用系统标签白名单。
        tags.update(re.findall(r"(?<!\S)#([^\s#]+)", content))
        return tags
