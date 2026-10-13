"""每周联系提醒的生成策略。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from personal_crm.core.domain import ensure_utc, utcnow
from personal_crm.core.ports import ReminderRepositoryPort


class ReminderService:
    """从人物联系节奏生成低负担提醒。"""

    def __init__(self, repository: ReminderRepositoryPort) -> None:
        self.repo = repository

    @staticmethod
    def _yearly_due(template: Any, year: int) -> datetime:
        """把年度提醒投影到目标年份；2 月 29 日在平年落到 2 月 28 日。"""

        try:
            return template.due_at.replace(year=year)
        except ValueError:
            return template.due_at.replace(year=year, day=28)

    def _materialize_yearly(self, current: datetime) -> None:
        """为进入未来七天窗口的年度重要日期创建新周期记录。"""

        templates = self.repo.list_yearly_important_reminders()
        window_end = current + timedelta(days=7)
        for template in templates:
            target = self._yearly_due(template, current.year)
            if target < current:
                target = self._yearly_due(template, current.year + 1)
            if target >= window_end:
                continue
            existing = self.repo.find_reminder_cycle(
                template.person_id, template.reminder_type, target
            )
            if existing is not None:
                continue
            # 新建记录而非复用旧记录，确保上一周期的完成率不会被回写。
            self.repo.create_reminder(
                person_id=template.person_id,
                reminder_type=template.reminder_type,
                due_at=target,
                reason=template.reason,
                suggested_message=template.suggested_message,
                recurrence_rule="yearly",
                created_at=current,
                updated_at=current,
            )

    def generate_weekly(self, now: datetime | None = None, limit: int = 3) -> list[Any]:
        """每周最多生成三条提醒，重要日期优先，普通提醒按逾期程度排序。"""

        current = ensure_utc(now or utcnow())
        limit = min(max(limit, 0), 3)
        self._materialize_yearly(current)
        # 已存在的生日和纪念日属于显式重要日期，优先占用本周配额。
        selected = self.repo.list_open_important_reminders(
            current, current + timedelta(days=7), limit
        )
        week_start = (current - timedelta(days=current.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        generated_this_week = self.repo.count_follow_ups_created_between(
            week_start, week_start + timedelta(days=7)
        )
        remaining = limit - len(selected) - generated_this_week
        if remaining <= 0:
            return selected

        candidates: list[tuple[float, Any, datetime]] = []
        for person in self.repo.list_active_cadence_people():
            if self.repo.has_open_follow_up(person.id):
                continue
            base = person.last_interaction_at or person.created_at
            due_at = base + timedelta(days=person.contact_interval_days or 0)
            if due_at > current + timedelta(days=7):
                continue
            overdue_seconds = (current - due_at).total_seconds()
            candidates.append((overdue_seconds, person, due_at))

        candidates.sort(key=lambda row: row[0], reverse=True)
        for _, person, due_at in candidates[:remaining]:
            reminder = self.repo.create_reminder(
                person_id=person.id,
                reminder_type="follow_up",
                due_at=due_at,
                reason=f"距离上次互动已达到 {person.contact_interval_days} 天",
                suggested_message="最近想到你，近来怎么样？",
                created_at=current,
                updated_at=current,
            )
            selected.append(reminder)
        return selected


def generate_follow_up(repo, now: datetime | None = None, limit: int = 3) -> list[Any]:
    """兼容早期调用方式的每周提醒入口。"""

    return ReminderService(repo).generate_weekly(now, limit)
