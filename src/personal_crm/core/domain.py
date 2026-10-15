"""与存储实现无关的个人 CRM 领域值和时间规则。"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime


def utcnow() -> datetime:
    """返回带 UTC 时区的当前时间。"""

    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """把输入时间统一为 UTC；无时区输入按 UTC 解释。"""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def uuid7() -> str:
    """生成符合 RFC 9562 布局、可按毫秒时间排序的 UUIDv7。"""

    timestamp_ms = int(utcnow().timestamp() * 1000) & ((1 << 48) - 1)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (secrets.randbits(12) << 64)
        | (0b10 << 62)
        | secrets.randbits(62)
    )
    return str(uuid.UUID(int=value))
