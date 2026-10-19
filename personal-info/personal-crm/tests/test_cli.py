from sqlalchemy import create_engine, inspect, text

from personal_crm.app.cli import main


def test_fresh_database_only_has_current_archive(tmp_path, monkeypatch, pg_database):
    url, _ = pg_database
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CRM_ASSET_ROOT", str(tmp_path / "assets"))
    assert main(["migrate"]) == 0
    assert main(["integrity"]) == 0
    tables = set(inspect(create_engine(url)).get_table_names())
    assert "crm_people" in tables and "crm_message_receipts" in tables
    assert not tables & {"people", "interactions", "facts", "reminders", "hub_records"}


def test_existing_current_schema_migration_is_repeatable(tmp_path, monkeypatch, pg_database):
    url, engine = pg_database
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CRM_ASSET_ROOT", str(tmp_path / "assets"))
    assert main(["migrate"]) == 0
    assert main(["migrate"]) == 0
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "004_person_archive"
