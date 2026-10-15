"""旧 CRM 冻结表定义；只供历史迁移、备份和旧数据清理使用。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from personal_crm.core.domain import (
    FactStatus,
    PersonStatus,
    ReminderStatus,
    ensure_utc,
    utcnow,
    uuid7,
)


class UTCDateTime(TypeDecorator[datetime]):
    """在 SQLite 中以无时区 UTC 保存，读取时恢复 UTC 时区。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        """写库前统一时区，并去掉 SQLite 无法可靠保存的 tzinfo。"""

        if value is None: return None
        return ensure_utc(value).replace(tzinfo=None) if dialect.name == "sqlite" else ensure_utc(value)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        """读库后恢复明确的 UTC 时区。"""

        del dialect
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类。"""


class Person(Base):
    """稳定的人物资料；快变量放 Interaction 或 Fact。"""

    __tablename__ = "people"
    __table_args__ = (
        CheckConstraint("json_valid(aliases)", name="ck_people_aliases_json").ddl_if(dialect="sqlite"),
        CheckConstraint("json_valid(contact_methods)", name="ck_people_contacts_json").ddl_if(dialect="sqlite"),
        CheckConstraint("json_valid(organizations)", name="ck_people_orgs_json").ddl_if(dialect="sqlite"),
        CheckConstraint("json_valid(tags)", name="ck_people_tags_json").ddl_if(dialect="sqlite"),
        CheckConstraint("status IN ('active','paused','archived')", name="ck_people_status"),
        CheckConstraint(
            "contact_interval_days IS NULL OR contact_interval_days > 0",
            name="ck_people_interval",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    pronouns: Mapped[str | None] = mapped_column(String(80))
    contact_methods: Mapped[dict[str, list[str]]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PersonStatus.ACTIVE.value
    )
    relationship_to_me: Mapped[str | None] = mapped_column(String(200))
    organizations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_interaction_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    contact_interval_days: Mapped[int | None] = mapped_column(Integer)
    profile_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )


class Interaction(Base):
    """互动查询兼容表；微信源消息以 JSON 原样保存。"""

    __tablename__ = "interactions"
    __table_args__ = (
        UniqueConstraint("source_type", "source_event_key", name="uq_interaction_source_event"),
        Index("uq_interaction_source_message", "source_type", "source_message_key", unique=True),
        CheckConstraint(
            "interaction_type IN ('message','call','meeting','manual_note','other')",
            name="ck_interaction_type",
        ),
        CheckConstraint(
            "channel IN ('wechat','phone','in_person','email','manual','other')",
            name="ck_interaction_channel",
        ),
        CheckConstraint(
            "direction IN ('inbound','outbound','mutual')",
            name="ck_interaction_direction",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    person_id: Mapped[str] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    interaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str | None] = mapped_column(Text)
    source_event_key: Mapped[str | None] = mapped_column(String(128))
    # 服务器消息身份与设备数据库偏移分离；旧记录允许为空并在回放时补齐。
    source_message_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)


class SyncClient(Base):
    """连接器运行状态表；各客户端独立推进水位，不承载人物或消息正文。"""

    __tablename__ = "sync_clients"

    source: Mapped[str] = mapped_column(String(80), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_batch_id: Mapped[str | None] = mapped_column(String(36))
    synced_through: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    accepted_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Fact(Base):
    """Agent 自动确认、但保留证据与撤回能力的人物事实。"""

    __tablename__ = "facts"
    __table_args__ = (
        UniqueConstraint(
            "person_id", "fact_type", "content_hash", name="uq_fact_person_type_content"
        ),
        CheckConstraint(
            "fact_type IN ('preference','boundary','life_event','organization','contact','other')",
            name="ck_fact_type",
        ),
        CheckConstraint("status IN ('active','superseded','retracted')", name="ck_fact_status"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_fact_confidence",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    person_id: Mapped[str] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=FactStatus.ACTIVE.value)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_interaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("interactions.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )


class Reminder(Base):
    """可追踪完成、跳过和周期规则的联系提醒。"""

    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            "reminder_type IN ('follow_up','birthday','anniversary','custom')",
            name="ck_reminder_type",
        ),
        CheckConstraint(
            "status IN ('pending','completed','snoozed','skipped','cancelled','expired')",
            name="ck_reminder_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid7)
    person_id: Mapped[str] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reminder_type: Mapped[str] = mapped_column(String(30), nullable=False)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ReminderStatus.PENDING.value
    )
    recurrence_rule: Mapped[str | None] = mapped_column(String(100))
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completion_interaction_id: Mapped[str | None] = mapped_column(
        ForeignKey("interactions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), nullable=False, default=utcnow, onupdate=utcnow
    )
