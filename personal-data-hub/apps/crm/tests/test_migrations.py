"""迁移到新归档，保留旧库只读转换来源。"""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_blank_database_upgrade_and_schema_check(tmp_path):
    root=Path(__file__).resolve().parents[1]
    config=Config(root/'alembic.ini')
    config.set_main_option('script_location',str(root/'migrations'))
    config.set_main_option('sqlalchemy.url','sqlite:///'+str(tmp_path/'migration.db'))
    command.upgrade(config,'head')
    engine=create_engine('sqlite:///'+str(tmp_path/'migration.db'))
    assert {'crm_people','crm_interactions','crm_message_receipts','people','interactions'} <= set(inspect(engine).get_table_names())
    with engine.connect() as c:
        assert c.scalar(text('SELECT version_num FROM alembic_version'))=='004_person_archive'
    command.check(config)
