"""来源游标的稳定编码与比较。"""

from __future__ import annotations

from datetime import datetime
import json

from review.domain import Evidence


def decode_cursor(value: str | None) -> tuple[datetime, str] | None:
    """解析 `(occurred_at, source_ref)` 游标；旧格式自动视为无游标。"""

    if not value:
        return None
    try:
        payload = json.loads(value)
        occurred = datetime.fromisoformat(str(payload["occurred_at"]).replace("Z", "+00:00"))
        return occurred, str(payload.get("source_ref", ""))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def is_after_cursor(occurred_at: datetime, source_ref: str, value: str | None) -> bool:
    """判断一条来源记录是否严格晚于已成功提交的稳定游标。"""

    cursor = decode_cursor(value)
    if cursor is None:
        return True
    return (occurred_at, source_ref) > cursor


def encode_cursor(items: list[Evidence]) -> str | None:
    """按事件时间和稳定来源引用生成下一游标。"""

    if not items:
        return None
    latest = max(items, key=lambda item: (item.occurred_at, item.source_ref))
    return json.dumps(
        {"occurred_at": latest.occurred_at.isoformat(), "source_ref": latest.source_ref},
        ensure_ascii=False,
        separators=(",", ":"),
    )
