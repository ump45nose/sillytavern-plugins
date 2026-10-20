import pytest
from pydantic import SecretStr
from hub_api.settings import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(database=tmp_path / "hub.sqlite", dev_token=SecretStr("SENTINEL-DEV-SECRET"))

