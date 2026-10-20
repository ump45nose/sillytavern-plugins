"""与存储实现无关的个人 CRM 领域值和时间规则。"""

from __future__ import annotations

import enum
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


class PersonStatus(enum.StrEnum):
    """人物是否参与当前社交建议。"""

    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class InteractionType(enum.StrEnum):
    """互动的业务形式。"""

    MESSAGE = "message"
    CALL = "call"
    MEETING = "meeting"
    MANUAL_NOTE = "manual_note"
    OTHER = "other"


class InteractionChannel(enum.StrEnum):
    """互动发生的渠道。"""

    WECHAT = "wechat"
    PHONE = "phone"
    IN_PERSON = "in_person"
    EMAIL = "email"
    MANUAL = "manual"
    OTHER = "other"


class InteractionDirection(enum.StrEnum):
    """互动方向，用于判断是否完成主动联系提醒。"""

    INBOUND = "inbound"
    OUTBOUND = "outbound"
    MUTUAL = "mutual"


class FactStatus(enum.StrEnum):
    """事实生命周期；首版事实默认自动生效。"""

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class ReminderType(enum.StrEnum):
    """提醒类别。"""

    FOLLOW_UP = "follow_up"
    BIRTHDAY = "birthday"
    ANNIVERSARY = "anniversary"
    CUSTOM = "custom"


class ReminderStatus(enum.StrEnum):
    """提醒生命周期。"""

    PENDING = "pending"
    COMPLETED = "completed"
    SNOOZED = "snoozed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
