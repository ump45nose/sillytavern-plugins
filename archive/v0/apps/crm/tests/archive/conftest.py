import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from personal_crm.archive import Archive


@pytest.fixture
def archive(tmp_path):
    url = os.environ.get("CRM_TEST_DATABASE_URL")
    if url:
        base = create_engine(url)
        schema = "test_crm_" + uuid4().hex
        with base.begin() as c:
            c.execute(text("CREATE SCHEMA " + schema))
        engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
        a = Archive(engine=engine, asset_root=tmp_path)
        yield a
        engine.dispose()
        with base.begin() as c:
            c.execute(text("DROP SCHEMA " + schema + " CASCADE"))
        base.dispose()
    else:
        a = Archive("sqlite:///" + str(tmp_path / "test.db"), tmp_path / "files")
        yield a
        a.engine.dispose()
