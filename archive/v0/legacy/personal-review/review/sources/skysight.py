"""读取 Skysight 分时摘要及其详细记录，供日报综合。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor


class SkysightSummarySource:
    """把每份上游 Memory summary 区块原样作为一个候选资料块。"""

    def __init__(self, root: str | Path) -> None:
        """记录 NAS 数据根目录。"""

        self.root = Path(root)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """优先使用覆盖对应时段的 6 小时记录，并以 10 分钟记录补齐空档。"""

        directory = self.root / "derived" / "skysight" / "source-summaries"
        if not directory.is_dir():
            return SourceResult("skysight", warnings=["Skysight 当日派生摘要未就绪"])

        paths = [path for path in sorted(directory.glob("*-memory-summary.md")) if self._in_window(path, window)]
        six_hour_paths = [path for path in paths if "-6h-memory-summary.md" in path.name]
        six_hour_starts = [self._filename_time(path.name) for path in six_hour_paths]
        selected_paths = [
            path for path in paths
            if path in six_hour_paths or not any(
                start is not None and start <= self._filename_time(path.name) < start + timedelta(hours=6)
                for start in six_hour_starts
            )
        ]
        evidence: list[Evidence] = []
        for path in selected_paths:
            occurred = self._filename_time(path.name)
            if occurred is None or not is_after_cursor(occurred, path.name, checkpoint):
                continue
            document = path.read_text(encoding="utf-8", errors="replace").strip()
            summary = self._memory_summary(document)
            recording = self._recording_summary(document)
            if not summary and not recording:
                continue
            summary_type = "6h" if "-6h-memory-summary.md" in path.name else "10min"
            period = self._period(occurred.astimezone(window.start.tzinfo).hour)
            evidence.append(
                Evidence(
                    stable_evidence_id("skysight-summary", occurred.isoformat(), path.name),
                    "skysight",
                    EvidenceKind.DELIVERY,
                    occurred,
                    f"Skysight {period}记录（上游 {summary_type}）",
                    subject=path.name,
                    source_ref=path.name,
                    payload={
                        "evidence_type": "source_summary",
                        "summary_type": summary_type,
                        "summary_markdown": "\n\n".join(
                            part for part in (summary, recording) if part
                        ),
                    },
                )
            )
        warning = [] if evidence else ["Skysight 窗口内没有可用上游摘要"]
        return SourceResult("skysight", evidence, warning, encode_cursor(evidence))

    @staticmethod
    def _memory_summary(document: str) -> str:
        """逐字提取上游 `Memory summary` 区块，不执行二次摘要或句子筛选。"""

        match = re.search(r"(?ms)^## Memory summary\s*\n(.*?)(?=^##\s|\Z)", document)
        if match:
            body = match.group(1).strip()
            # 上游把检索背景和实体词典放在同一二级标题下；它们不是当日行为摘要，日报必须截断。
            body = re.split(
                r"(?mi)^(?:#{1,6}\s*)?(?:Relevant prior context|Important non-obvious context about the user)\s*$",
                body,
                maxsplit=1,
            )[0].strip()
            return "## Memory summary\n" + body
        if "## Recording summary" in document:
            return ""
        # 兼容旧派生文件：没有结构化标题时，整份文件本身即视为上游摘要。
        return document.strip()

    @staticmethod
    def _recording_summary(document: str) -> str:
        """提取上游详细记录，排除引用、检索背景与原始事件。"""

        match = re.search(r"(?ms)^## Recording summary\s*\n(.*?)(?=^##\s|\Z)", document)
        return "## Recording summary\n" + match.group(1).strip() if match and match.group(1).strip() else ""

    @staticmethod
    def _period(hour: int) -> str:
        """按业务时区给上游摘要添加稳定的人类时间段标签。"""

        if 5 <= hour < 12:
            return "上午"
        if 12 <= hour < 18:
            return "下午"
        if 18 <= hour < 24:
            return "晚上"
        return "凌晨"

    @classmethod
    def _in_window(cls, path: Path, window: TimeWindow) -> bool:
        """判断摘要文件时间是否落入冻结窗口。"""

        occurred = cls._filename_time(path.name)
        if occurred is None:
            return False
        local = occurred.astimezone(window.start.tzinfo)
        return window.start <= local < window.end

    @staticmethod
    def _filename_time(name: str) -> datetime | None:
        """从 UTC 文件名前缀解析摘要时间。"""

        match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-", name)
        if not match:
            return None
        try:
            return datetime.strptime(match.group(1), "%Y-%m-%dT%H-%M-%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
