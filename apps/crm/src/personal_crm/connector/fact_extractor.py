"""微信正文的本机 Fact 抽取边界。"""

from __future__ import annotations

import re
from typing import Protocol


class FactExtractor(Protocol):
    """定义可替换的本机 Fact 抽取器，原始正文不得由实现持久化或外发。"""

    def extract(self, text: str, direction: str) -> list[dict[str, object]]:
        """从单条短生命周期正文返回受限结构化事实。"""


class NullFactExtractor:
    """默认关闭状态的空抽取器。"""

    def extract(self, text: str, direction: str) -> list[dict[str, object]]:
        """保持隐私默认值，不生成任何 Fact。"""

        return []


class RuleBasedFactExtractor:
    """只识别对方明确自述的高置信事实，避免把闲聊推断成人物画像。"""

    _TAIL = r"([^，。！？!?；;\n]{1,48})"
    _RULES = (
        (
            "preference",
            re.compile(rf"(?:^|[，。！？!?；;\s])我(?:最)?(喜欢|偏好|爱吃|爱喝){_TAIL}"),
            0.92,
        ),
        (
            "preference",
            re.compile(rf"(?:^|[，。！？!?；;\s])我(不喜欢|不爱吃|不爱喝|不吃|不喝){_TAIL}"),
            0.92,
        ),
        (
            "boundary",
            re.compile(rf"(?:^|[，。！？!?；;\s])我(不能接受|很介意|的底线是){_TAIL}"),
            0.94,
        ),
        (
            "life_event",
            re.compile(
                r"(?:^|[，。！？!?；;\s])我(?:已经|刚刚?|准备|打算|计划|快要|要)?"
                r"(结婚|订婚|毕业|入职|离职|搬家|怀孕|生孩子|换工作|出国|回国)"
            ),
            0.9,
        ),
        (
            "organization",
            re.compile(
                r"(?:^|[，。！？!?；;\s])我在"
                r"([\u4e00-\u9fffA-Za-z0-9·&（）() -]{2,40})"
                r"(?:上班|工作|读书|学习)"
            ),
            0.9,
        ),
        (
            "contact",
            re.compile(r"(?:我的?(?:手机号|电话)是|联系我[:：]?\s*)(1[3-9]\d{9})"),
            0.98,
        ),
        (
            "contact",
            re.compile(
                r"(?:我的?邮箱是|联系我[:：]?\s*)"
                r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
            ),
            0.98,
        ),
    )

    def extract(self, text: str, direction: str) -> list[dict[str, object]]:
        """仅从 inbound 纯文本中抽取，每种类型每条消息最多生成一个事实。"""

        if direction != "inbound":
            return []
        normalized = " ".join(str(text or "").strip().split())
        # XML、JSON、链接和超长内容多为卡片或转发，不作为对方自述处理。
        if (
            not normalized
            or len(normalized) > 500
            or normalized.startswith(("<", "{"))
            or "http://" in normalized
            or "https://" in normalized
        ):
            return []

        facts: list[dict[str, object]] = []
        seen_types: set[str] = set()
        for fact_type, pattern, confidence in self._RULES:
            if fact_type in seen_types:
                continue
            match = pattern.search(normalized)
            if not match:
                continue
            # 输出最小必要事实片段，不复制整条微信正文。
            content = "".join(part.strip() for part in match.groups() if part).strip()
            if not content:
                continue
            facts.append(
                {
                    "fact_type": fact_type,
                    "content": content[:120],
                    "confidence": confidence,
                }
            )
            seen_types.add(fact_type)
        return facts
