import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from personal_crm.archive import Archive


@pytest.fixture(autouse=True)
def settings_database(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get("CRM_TEST_DATABASE_URL", "postgresql+psycopg://localhost/crm_test"),
    )


@pytest.fixture
def pg_database():
    url = os.environ.get("CRM_TEST_DATABASE_URL")
    if not url:
        pytest.fail("CRM_TEST_DATABASE_URL must point to PostgreSQL")
    base = create_engine(url)
    schema = "test_crm_" + uuid4().hex
    with base.begin() as c:
        c.execute(text("CREATE SCHEMA " + schema))
    scoped = (
        make_url(url)
        .update_query_dict({"options": "-csearch_path=" + schema})
        .render_as_string(hide_password=False)
    )
    engine = create_engine(scoped)
    try:
        yield scoped, engine
    finally:
        engine.dispose()
        with base.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        base.dispose()


@pytest.fixture
def archive(pg_database, tmp_path):
    _, engine = pg_database
    a = Archive(engine=engine, asset_root=tmp_path)
    yield a
