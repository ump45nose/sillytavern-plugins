import importlib.util

from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings


def test_standalone_does_not_load_host_features(archive):
    assert importlib.util.find_spec("personal_data_hub") is None
    with TestClient(create_app(Settings(mcp_development_no_auth=True), archive)) as client:
        assert client.get("/healthz").json() == {"status": "ok", "database": "ok"}
        assert client.get("/api/v1/daily-push").status_code == 404
        assert client.get("/personal-review").status_code == 404


def test_database_result_respects_actual_timezone():
    from datetime import UTC, datetime, timedelta, timezone

    from personal_crm.archive.models import UTCDateTime

    local = datetime(2026, 10, 15, 10, tzinfo=timezone(timedelta(hours=8)))
    assert UTCDateTime().process_result_value(local, None) == datetime(2026, 10, 15, 2, tzinfo=UTC)
