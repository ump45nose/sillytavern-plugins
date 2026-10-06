"""Alembic 初始迁移与版本标记测试。"""

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine


def test_blank_database_upgrade_records_head(tmp_path):
    """验证空库升级不仅创建四表，也会持久化 Alembic head。"""

    database = tmp_path / "migration.db"
    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    with create_engine(f"sqlite:///{database}").connect() as connection:
        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    assert {"people", "interactions", "facts", "reminders"} <= tables
    assert "sync_clients" in tables
    assert version == "002_sync_clients"
    command.check(config)


def test_existing_database_upgrade_preserves_legacy_interaction(tmp_path):
    """验证老版四表升级保留互动，新增可空身份列及唯一索引。"""

    from personal_crm.storage import CrmRepository

    database = tmp_path / "existing.db"
    project_root = Path(__file__).resolve().parents[1]
    config = Config(project_root / "alembic.ini")
    config.set_main_option("script_location", str(project_root / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    repo = CrmRepository(f"sqlite:///{database}")
    person = repo.create_person(display_name="迁移保留测试")
    interaction, _, _ = repo.record_interaction(
        person_id=person.id,
        occurred_at=datetime(2026, 9, 4, tzinfo=UTC),
        interaction_type="message",
        channel="wechat",
        direction="inbound",
        summary="迁移保留摘要",
        source_type="chatlog",
        source_event_key="legacy-key",
    )
    repo.engine.dispose()
    # 回退技术状态模拟部署中的 001_initial，再从该结构升级。
    command.downgrade(config, "001_initial")
    command.upgrade(config, "head")
    restored = CrmRepository(f"sqlite:///{database}")
    assert restored.get_person(person.id).display_name == "迁移保留测试"
    assert restored.list_interactions()[0].id == interaction.id
    assert restored.list_interactions()[0].source_message_key is None
    command.check(config)
