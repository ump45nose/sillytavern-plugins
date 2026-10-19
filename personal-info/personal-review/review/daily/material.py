"""日报材料的结构化展示模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DailyMaterialSection:
    """表示一个可选 Markdown 二级分区。"""

    title: str
    blocks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """转换为供 Agent 使用的无来源元数据结构。"""

        return {"title": self.title, "blocks": list(self.blocks)}


@dataclass(frozen=True)
class DailyMaterialBundle:
    """同时承载用户材料和仅供诊断的来源状态。"""

    day: str
    sections: tuple[DailyMaterialSection, ...]
    template: str
    source_status: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self, include_internal: bool = False) -> dict[str, Any]:
        """输出机器可读材料；内部来源状态默认不向 Agent 暴露。"""

        result: dict[str, Any] = {
            "day": self.day,
            "sections": [section.to_dict() for section in self.sections],
            "template": self.template,
        }
        if include_internal:
            result["source_status"] = self.source_status
        return result

    def to_markdown(self) -> str:
        """确定性渲染精简 Markdown，作为正常输出和故障回退。"""

        lines = [f"# 今日日报材料｜{self.day}"]
        for section in self.sections:
            if not section.blocks:
                continue
            lines.extend(["", f"## {section.title}", ""])
            lines.append("\n\n".join(block.strip() for block in section.blocks if block.strip()))
        lines.extend(["", "## 日报草稿", "", self.template])
        return "\n".join(lines).strip()
