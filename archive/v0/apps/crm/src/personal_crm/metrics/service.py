"""Reminder 周绩效计算。"""

from __future__ import annotations

from datetime import datetime, timedelta

from personal_crm.core.domain import ensure_utc
from personal_crm.core.ports import MetricsRepositoryPort


def weekly_metrics(
    repository: MetricsRepositoryPort, week_start: datetime, week_end: datetime | None = None
) -> dict:
    """统计到期、完成与跳过；取消项不进入分母。"""

    start = ensure_utc(week_start)
    end = ensure_utc(week_end) if week_end else start + timedelta(days=7)
    reminders = repository.list_reminders_due_between(start, end, excluded_statuses={"cancelled"})
    due_count = len(reminders)
    completed_count = sum(item.status == "completed" for item in reminders)
    skipped_count = sum(item.status == "skipped" for item in reminders)
    return {
        "due_count": due_count,
        "completed_count": completed_count,
        "skipped_count": skipped_count,
        "completion_rate": completed_count / due_count if due_count else 0.0,
    }
