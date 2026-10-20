"""CRM 应用服务：在 MCP、Webhook 与存储之间统一业务校验。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .domain import (
    FactStatus,
    InteractionChannel,
    InteractionDirection,
    InteractionType,
    PersonStatus,
    ReminderStatus,
    ReminderType,
    ensure_utc,
    utcnow,
)
from .ports import RepositoryPort


def _enum_value(enum_type: type, value: str, field: str) -> str:
    """把字符串规范为枚举值，并给调用方返回稳定的字段错误。"""

    try:
        return enum_type(value).value
    except ValueError as error:
        raise ValueError(f"invalid {field}: {value}") from error


class CrmService:
    """供不同传输层复用的个人 CRM 用例入口。"""

    def __init__(self, repository: RepositoryPort) -> None:
        self.repo = repository

    def upsert_person(
        self,
        *,
        person_id: str | None = None,
        display_name: str,
        aliases: list[str] | None = None,
        pronouns: str | None = None,
        contact_methods: dict[str, list[str]] | None = None,
        status: str = "active",
        relationship_to_me: str | None = None,
        organizations: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        contact_interval_days: int | None = None,
        profile_notes: str | None = None,
    ):
        """创建或更新人物，联系方式保持结构化 JSON。"""

        if not display_name.strip():
            raise ValueError("display_name is required")
        if contact_interval_days is not None and contact_interval_days <= 0:
            raise ValueError("contact_interval_days must be positive")
        normalized_contacts = {
            key: sorted({str(item).strip() for item in values if str(item).strip()})
            for key, values in (contact_methods or {}).items()
            if values
        }
        return self.repo.upsert_person(
            person_id,
            display_name=display_name.strip(),
            aliases=sorted({item.strip() for item in aliases or [] if item.strip()}),
            pronouns=pronouns,
            contact_methods=normalized_contacts,
            status=_enum_value(PersonStatus, status, "status"),
            relationship_to_me=relationship_to_me,
            organizations=organizations or [],
            tags=sorted({item.strip() for item in tags or [] if item.strip()}),
            contact_interval_days=contact_interval_days,
            profile_notes=profile_notes,
        )

    def create_person(self, display_name: str, **values: Any):
        """兼容命令行和测试的创建人物简写。"""

        return self.upsert_person(display_name=display_name, **values)[0]

    def get_person(self, person_id: str):
        """读取单个人物。"""

        return self.repo.get_person(person_id)

    def search_people(self, query: str = "", limit: int = 50):
        """搜索人物。"""

        return self.repo.search_people(query, limit)

    def merge_people(self, source_person_id: str, target_person_id: str):
        """合并重复人物，目标资料优先并保留双方全部业务历史。"""

        return self.repo.merge_people(source_person_id, target_person_id)

    def record_interaction(
        self,
        *,
        person_id: str,
        occurred_at: datetime,
        interaction_type: str = "message",
        channel: str = "manual",
        direction: str,
        summary: str,
        source_type: str = "manual",
        source_reference: str | None = None,
        source_event_key: str | None = None,
    ):
        """记录互动摘要；存储层同时处理幂等、末次互动和提醒完成。"""

        if not summary.strip():
            raise ValueError("summary is required")
        return self.repo.record_interaction(
            person_id=person_id,
            occurred_at=ensure_utc(occurred_at),
            interaction_type=_enum_value(InteractionType, interaction_type, "interaction_type"),
            channel=_enum_value(InteractionChannel, channel, "channel"),
            direction=_enum_value(InteractionDirection, direction, "direction"),
            summary=summary.strip(),
            source_type=source_type.strip() or "manual",
            source_reference=source_reference,
            source_event_key=source_event_key,
        )

    def record_fact(
        self,
        *,
        person_id: str,
        fact_type: str,
        content: str,
        observed_at: datetime | None = None,
        confidence: float | None = None,
        source_interaction_id: str | None = None,
    ):
        """自动确认一条带证据来源的事实。"""

        if not content.strip():
            raise ValueError("content is required")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        allowed = {"preference", "boundary", "life_event", "organization", "contact", "other"}
        if fact_type not in allowed:
            raise ValueError(f"invalid fact_type: {fact_type}")
        return self.repo.record_fact(
            person_id=person_id,
            fact_type=fact_type,
            content=content,
            observed_at=observed_at or utcnow(),
            confidence=confidence,
            source_interaction_id=source_interaction_id,
        )

    def update_fact_status(self, fact_id: str, status: str):
        """撤回、恢复或标记事实已被后续事实替代。"""

        return self.repo.update_fact_status(fact_id, _enum_value(FactStatus, status, "fact status"))

    def create_reminder(
        self,
        *,
        person_id: str,
        due_at: datetime,
        reason: str,
        reminder_type: str = "follow_up",
        suggested_message: str | None = None,
        recurrence_rule: str | None = None,
    ):
        """创建可衡量的提醒，不执行任何外部发送动作。"""

        if not reason.strip():
            raise ValueError("reason is required")
        return self.repo.create_reminder(
            person_id=person_id,
            reminder_type=_enum_value(ReminderType, reminder_type, "reminder_type"),
            due_at=ensure_utc(due_at),
            reason=reason.strip(),
            suggested_message=suggested_message,
            recurrence_rule=recurrence_rule,
        )

    def update_reminder_status(
        self,
        reminder_id: str,
        status: str,
        *,
        due_at: datetime | None = None,
    ):
        """更新提醒状态；手工完成时记录当前时间。"""

        normalized = _enum_value(ReminderStatus, status, "reminder status")
        values: dict[str, Any] = {"status": normalized}
        if due_at is not None:
            values["due_at"] = ensure_utc(due_at)
        if normalized == ReminderStatus.COMPLETED.value:
            values["completed_at"] = utcnow()
        return self.repo.update_reminder(reminder_id, **values)
