"""四表、幂等和自动完成规则测试。"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from personal_crm.core import CrmService
from personal_crm.storage import CrmRepository
from personal_crm.storage.models import uuid7


@pytest.fixture
def crm():
    """创建共享连接的内存 SQLite 服务。"""

    repository = CrmRepository("sqlite:///:memory:")
    return repository, CrmService(repository)


def test_four_tables_and_json_constraints(crm):
    """验证严格四表、JSON 默认值和数据库 JSON 约束。"""

    repository, service = crm
    person = service.create_person("小邱")
    assert person.aliases == []
    assert person.contact_methods == {}
    with repository.engine.begin() as connection:
        names = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"people", "interactions", "facts", "reminders"} <= names
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO people "
                "(id,display_name,aliases,contact_methods,status,organizations,tags,"
                "created_at,updated_at) VALUES "
                "('bad','bad','not-json','{}','active','[]','[]',"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )


def test_uuid7_and_utc_round_trip(crm):
    """验证 UUID 版本和带时区时间读写。"""

    repository, service = crm
    assert __import__("uuid").UUID(uuid7()).version == 7
    person = service.create_person("甲")
    entity, created, _ = service.record_interaction(
        person_id=person.id,
        occurred_at=datetime(2026, 9, 4, 1, tzinfo=UTC),
        direction="inbound",
        summary="收到问候",
    )
    assert created and entity.occurred_at.tzinfo == UTC
    assert repository.get_person(person.id).last_interaction_at.tzinfo == UTC


def test_interaction_idempotency_last_contact_and_reminder_completion(crm):
    """验证幂等、末次互动不倒退以及主动互动自动完成已有提醒。"""

    repository, service = crm
    person = service.create_person("乙")
    due = datetime(2026, 9, 5, tzinfo=UTC)
    reminder = service.create_reminder(person_id=person.id, due_at=due, reason="问候")
    first, created, completed = service.record_interaction(
        person_id=person.id,
        occurred_at=due + timedelta(days=1),
        direction="outbound",
        summary="已主动联系",
        source_type="test",
        source_event_key="event-1",
    )
    assert created and completed == 1
    duplicate, created, _ = service.record_interaction(
        person_id=person.id,
        occurred_at=due + timedelta(days=1),
        direction="outbound",
        summary="重复投递",
        source_type="test",
        source_event_key="event-1",
    )
    assert duplicate.id == first.id and not created
    service.record_interaction(
        person_id=person.id,
        occurred_at=due - timedelta(days=30),
        direction="inbound",
        summary="补录旧消息",
    )
    assert repository.get_person(person.id).last_interaction_at == due + timedelta(days=1)
    assert repository.get_reminder(reminder.id).status == "completed"


def test_inbound_and_late_interaction_do_not_complete(crm):
    """验证 inbound 与超过七天窗口的互动不完成提醒。"""

    repository, service = crm
    person = service.create_person("丙")
    due = datetime(2026, 9, 5, tzinfo=UTC)
    inbound = service.create_reminder(person_id=person.id, due_at=due, reason="问候")
    service.record_interaction(
        person_id=person.id,
        occurred_at=due,
        direction="inbound",
        summary="对方发来消息",
    )
    late = service.create_reminder(person_id=person.id, due_at=due, reason="再次问候")
    service.record_interaction(
        person_id=person.id,
        occurred_at=due + timedelta(days=8),
        direction="outbound",
        summary="过期后联系",
    )
    assert repository.get_reminder(inbound.id).status == "pending"
    assert repository.get_reminder(late.id).status == "pending"


def test_fact_is_idempotent_and_supersedes_same_type(crm):
    """验证事实自动生效、重复幂等和同类型替代。"""

    repository, service = crm
    person = service.create_person("丁")
    first, created = service.record_fact(
        person_id=person.id, fact_type="preference", content="喜欢咖啡"
    )
    duplicate, created_again = service.record_fact(
        person_id=person.id, fact_type="preference", content="喜欢咖啡"
    )
    second, _ = service.record_fact(
        person_id=person.id, fact_type="preference", content="最近不喝咖啡"
    )
    statuses = {item.id: item.status for item in repository.list_facts(person.id)}
    assert created and not created_again and duplicate.id == first.id
    assert statuses[first.id] == "superseded"
    assert statuses[second.id] == "active"


def test_backup_and_integrity(tmp_path):
    """验证文件数据库可备份并通过完整性检查。"""

    source = tmp_path / "crm.db"
    repository = CrmRepository(f"sqlite:///{source}")
    CrmService(repository).create_person("备份对象")
    target = repository.backup(tmp_path / "backup.db")
    assert target.exists() and repository.integrity_check() == "ok"
