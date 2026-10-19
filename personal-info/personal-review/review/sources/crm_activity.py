"""保存并读取 Personal CRM MCP 的每日关系变化汇总。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor


def _count_block(payload: dict[str, Any], key: str, nested: tuple[str, ...]) -> dict[str, Any]:
    """校验 MCP 聚合块，只允许下游需要的计数、人物名和分类计数。"""

    block = payload.get(key)
    if not isinstance(block, dict) or isinstance(block.get("count"), bool) or not isinstance(block.get("count"), int):
        raise ValueError(f"CRM MCP 汇总缺少 {key}.count")
    if block["count"] < 0:
        raise ValueError(f"CRM MCP 汇总 {key}.count 不能为负数")
    people = block.get("people", [])
    if not isinstance(people, list) or any(not isinstance(name, str) or not name.strip() for name in people):
        raise ValueError(f"CRM MCP 汇总 {key}.people 无效")
    result: dict[str, Any] = {"count": block["count"], "people": sorted(set(people))}
    for name in nested:
        values = block.get(name, {})
        if not isinstance(values, dict) or any(
            not isinstance(label, str) or isinstance(count, bool) or not isinstance(count, int) or count < 0
            for label, count in values.items()
        ):
            raise ValueError(f"CRM MCP 汇总 {key}.{name} 无效")
        result[name] = dict(sorted(values.items()))
    return result


def store_crm_mcp_summary(summary_dir: str | Path, day: str, payload: Any, generated_at: datetime) -> dict[str, Any]:
    """把 CRM MCP 的无正文结果规范化后原子落盘，供日报确定性读取。"""

    if not isinstance(payload, dict) or payload.get("date") != day:
        raise ValueError("CRM MCP 汇总日期不匹配")
    interactions = _count_block(payload, "interactions", ("directions", "channels"))
    facts = _count_block(payload, "facts", ("types",))
    reminders = _count_block(payload, "reminder_changes", ("statuses",))
    raw_content_summaries = payload.get("content_summaries", {})
    if not isinstance(raw_content_summaries, dict):
        raise ValueError("CRM MCP 汇总 content_summaries 无效")
    content_summaries: dict[str, list[str]] = {}
    for person, values in raw_content_summaries.items():
        if (
            not isinstance(person, str)
            or not person.strip()
            or not isinstance(values, list)
            or len(values) > 5
            or any(not isinstance(value, str) or not value.strip() or len(value) > 240 for value in values)
        ):
            raise ValueError("CRM MCP 汇总 content_summaries 无效")
        content_summaries[person.strip()] = list(dict.fromkeys(value.strip() for value in values))
    canonical = json.dumps(
        {
            "date": day,
            "interactions": interactions,
            "facts": facts,
            "reminder_changes": reminders,
            "content_summaries": content_summaries,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    summary = {
        "schema_version": 1,
        "date": day,
        "generated_at": generated_at.isoformat(),
        "interactions": interactions,
        "facts": facts,
        "reminder_changes": reminders,
        "content_summaries": content_summaries,
        "source_sha256": hashlib.sha256(canonical).hexdigest(),
    }
    destination = Path(summary_dir) / f"{day}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(destination)
    return {
        "date": day,
        "interaction_count": interactions["count"],
        "fact_count": facts["count"],
        "reminder_change_count": reminders["count"],
    }


class CrmActivitySource:
    """把一个业务日的 CRM 聚合快照载入为单个自动日报字段。"""

    def __init__(self, summary_dir: str | Path) -> None:
        """绑定只允许保存无正文 CRM 汇总的目录。"""

        self.summary_dir = Path(summary_dir)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        """读取当天聚合；零变化是有效结果，缺文件才提示来源未就绪。"""

        del checkpoint
        day = window.start.date().isoformat()
        path = self.summary_dir / f"{day}.json"
        if not path.is_file():
            return SourceResult("crm", warnings=["本日没有 CRM 汇总"])
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("schema_version") != 1 or summary.get("date") != day:
            return SourceResult("crm", warnings=["本日 CRM 汇总格式无效"])
        occurred_at = datetime.fromisoformat(str(summary["generated_at"]))
        fact = self._render(summary)
        evidence = Evidence(
            stable_evidence_id("crm", day, str(summary["source_sha256"])),
            "crm",
            EvidenceKind.RELATIONSHIP,
            occurred_at,
            fact,
            source_ref=f"crm-mcp:{day}@{summary['source_sha256']}",
            payload={
                "change_count": sum(
                    int(summary[key]["count"])
                    for key in ("interactions", "facts", "reminder_changes")
                ),
                "people": sorted(
                    {
                        person
                        for key in ("interactions", "facts", "reminder_changes")
                        for person in summary[key].get("people", [])
                    }
                ),
            },
        )
        return SourceResult("crm", [evidence], next_checkpoint=encode_cursor([evidence]))

    @staticmethod
    def _render(summary: dict[str, Any]) -> str:
        """把结构化关系变化压成一行，禁止展开 CRM 私密正文。"""

        interactions = summary["interactions"]
        facts = summary["facts"]
        reminders = summary["reminder_changes"]
        if not any((interactions["count"], facts["count"], reminders["count"])):
            return "今日 CRM 无关系变化"
        parts: list[str] = []
        if interactions["count"]:
            people = "、".join(interactions["people"])
            parts.append(f"互动 {interactions['count']} 次 / {len(interactions['people'])} 人" + (f"（{people}）" if people else ""))
        if facts["count"]:
            parts.append(f"新增事实 {facts['count']} 条")
        if reminders["count"]:
            statuses = "、".join(f"{name} {count}" for name, count in reminders["statuses"].items())
            parts.append(f"提醒变化 {reminders['count']} 项" + (f"（{statuses}）" if statuses else ""))
        content_summaries = summary.get("content_summaries", {})
        if content_summaries:
            rendered = []
            for person, values in content_summaries.items():
                rendered.append(f"{person}：{'；'.join(values)}")
            parts.append("内容摘要 " + " / ".join(rendered))
        return "；".join(parts)
