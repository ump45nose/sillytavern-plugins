from sqlalchemy import create_engine, inspect, text

from personal_crm.app.cli import main


def test_fresh_database_only_has_current_archive(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "crm.db")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CRM_ASSET_ROOT", str(tmp_path / "assets"))
    assert main(["migrate"]) == 0
    assert main(["migrate-legacy"]) == 0
    assert main(["integrity"]) == 0
    assert main(["backup", str(tmp_path / "backup.db")]) == 0
    assert (tmp_path / "backup.db").is_file()
    tables = set(inspect(create_engine(url)).get_table_names())
    assert "crm_people" in tables and "crm_message_receipts" in tables
    assert not tables & {"people", "interactions", "facts", "reminders", "hub_records"}


def test_existing_003_database_can_upgrade_without_recreating_legacy(tmp_path, monkeypatch):
    url = "sqlite:///" + str(tmp_path / "existing.db")
    engine = create_engine(url)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE alembic_version(version_num VARCHAR(32) PRIMARY KEY)"))
        c.execute(text("INSERT INTO alembic_version VALUES('003_wechat_messages')"))
        c.execute(text("CREATE TABLE people(id TEXT PRIMARY KEY, display_name TEXT)"))
        c.execute(text("INSERT INTO people VALUES('legacy','保留')"))
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CRM_ASSET_ROOT", str(tmp_path / "assets"))
    assert main(["migrate"]) == 0
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "004_person_archive"
        assert c.scalar(text("SELECT display_name FROM people")) == "保留"
    assert "crm_people" in inspect(engine).get_table_names()
    assert "reminders" not in inspect(engine).get_table_names()
