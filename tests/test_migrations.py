"""Alembic 初始迁移与版本标记测试。"""

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
    assert version == "001_initial"
    command.check(config)
