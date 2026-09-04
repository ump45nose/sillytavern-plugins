"""Reminder 生成与周绩效测试。"""

from datetime import UTC, datetime, timedelta

from personal_crm.core import CrmService
from personal_crm.metrics import weekly_metrics
from personal_crm.reminders import ReminderService
from personal_crm.storage import CrmRepository


def test_weekly_generation_caps_at_three_and_prioritizes_important_date():
    """验证每周上限和重要日期优先。"""

    repository = CrmRepository("sqlite:///:memory:")
    service = CrmService(repository)
    now = datetime(2026, 9, 7, tzinfo=UTC)
    people = [
        service.create_person(f"联系人{index}", contact_interval_days=1) for index in range(4)
    ]
    important = service.create_reminder(
        person_id=people[-1].id,
        due_at=now + timedelta(days=1),
        reason="生日",
        reminder_type="birthday",
        recurrence_rule="yearly",
    )
    generated = ReminderService(repository).generate_weekly(now)
    assert len(generated) == 3
    assert important.id in {item.id for item in generated}
    # 同一周重复调度不得为剩余联系人继续追加，周预算仍为三条。
    ReminderService(repository).generate_weekly(now + timedelta(days=1))
    assert len(repository.list_reminders()) == 3


def test_weekly_metrics_uses_controllable_actions_only():
    """验证取消项不进分母，完成和跳过分别统计。"""

    repository = CrmRepository("sqlite:///:memory:")
    service = CrmService(repository)
    start = datetime(2026, 9, 7, tzinfo=UTC)
    person = service.create_person("指标对象")
    completed = service.create_reminder(person_id=person.id, due_at=start, reason="完成")
    skipped = service.create_reminder(
        person_id=person.id, due_at=start + timedelta(days=1), reason="跳过"
    )
    cancelled = service.create_reminder(
        person_id=person.id, due_at=start + timedelta(days=2), reason="取消"
    )
    service.update_reminder_status(completed.id, "completed")
    service.update_reminder_status(skipped.id, "skipped")
    service.update_reminder_status(cancelled.id, "cancelled")
    assert weekly_metrics(repository, start) == {
        "due_count": 2,
        "completed_count": 1,
        "skipped_count": 1,
        "completion_rate": 0.5,
    }


def test_yearly_reminder_creates_new_cycle_without_rewriting_history():
    """验证年度提醒会生成新记录，并保留上一周期绩效状态。"""

    repository = CrmRepository("sqlite:///:memory:")
    service = CrmService(repository)
    person = service.create_person("年度联系人")
    previous = service.create_reminder(
        person_id=person.id,
        due_at=datetime(2025, 9, 10, tzinfo=UTC),
        reason="生日",
        reminder_type="birthday",
        recurrence_rule="yearly",
    )
    service.update_reminder_status(previous.id, "completed")
    generated = ReminderService(repository).generate_weekly(datetime(2026, 9, 7, tzinfo=UTC))
    current = next(item for item in generated if item.reminder_type == "birthday")
    assert current.id != previous.id
    assert current.due_at == datetime(2026, 9, 10, tzinfo=UTC)
    assert repository.get_reminder(previous.id).status == "completed"
