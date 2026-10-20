"""读取 Skysight 分时摘要及其详细记录，供日报综合。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import subprocess
from pathlib import Path
import re

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor, is_after_cursor


class SkysightSummarySource:
    """把每份上游 Memory summary 区块原样作为一个候选资料块。"""

    def __init__(self, root: str | Path, reader: str | Path | None = None) -> None:
        """记录 NAS 数据根目录。"""

        self.root = Path(root)
        self.reader = Path(reader) if reader else None

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """读取独立同步程序已发布的清单；每台设备独立选择 6h/10min。"""
        if self.reader:
            request = {"start": window.start.isoformat(), "end": window.end.isoformat(), "checkpoint": checkpoint}
            result = subprocess.run([str(self.reader)], input=json.dumps(request), text=True,
                                    capture_output=True, timeout=60, check=True)
            payload = json.loads(result.stdout)
            evidence = [Evidence(**{**row, "kind": EvidenceKind(row["kind"]),
                                    "occurred_at": datetime.fromisoformat(row["occurred_at"])})
                        for row in payload["evidence"]]
            return SourceResult("skysight", evidence, payload["warnings"], payload["next_checkpoint"])
        manifests = sorted((self.root / "devices").glob("*/manifest.json"))
        if not manifests:
            raise FileNotFoundError("Skysight 同步归档清单不存在")
        evidence, warnings = [], []
        for manifest in manifests:
            device = manifest.parent.name
            entries = json.loads(manifest.read_text())["entries"]
            candidates = []
            for name, entry in entries.items():
                start = self._filename_time(name)
                if start is None:
                    continue
                duration = timedelta(hours=6) if "-6h-" in name else timedelta(minutes=10)
                finish = start + duration
                if start < window.end and finish > window.start and finish <= window.end:
                    candidates.append((name, entry, start, finish))
            long = [(start, end) for name, _, start, end in candidates if "-6h-" in name]
            selected = [row for row in candidates if "-6h-" in row[0]
                        or not any(start <= row[2] and row[3] <= end for start, end in long)]
            if not selected:
                warnings.append(f"Skysight {device} 当前窗口没有已同步摘要")
            for name, entry, start, finish in sorted(selected):
                if Path(name).name != name or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                    raise ValueError("Skysight 清单包含无效归档路径")
                path = manifest.parent / "objects" / entry["sha256"] / name
                document = path.read_text(encoding="utf-8")
                summary, recording = self._memory_summary(document), self._recording_summary(document)
                if not summary and not recording:
                    continue
                occurred = max(start, window.start)
                if not is_after_cursor(occurred, f"{device}:{name}", checkpoint):
                    continue
                local_start, local_end = start.astimezone(window.start.tzinfo), finish.astimezone(window.start.tzinfo)
                text = f"### {device}｜{local_start:%m-%d %H:%M}–{local_end:%m-%d %H:%M}\n\n" + "\n\n".join(
                    value for value in (summary, recording) if value)
                evidence.append(Evidence(
                    stable_evidence_id("skysight-summary", occurred.isoformat(), f"{device}:{name}"),
                    "skysight", EvidenceKind.DELIVERY, occurred,
                    f"Skysight {device} {self._period(local_start.hour)}记录",
                    subject=f"{device}:{name}", source_ref=f"{device}:{name}",
                    payload={"evidence_type": "source_summary", "summary_type": "6h" if "-6h-" in name else "10min",
                             "summary_markdown": text},
                ))
        return SourceResult("skysight", evidence, warnings, encode_cursor(evidence))

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
