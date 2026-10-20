from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HUB_", extra="ignore")
    database: Path = Path("/data/hub.sqlite")
    dev_token: SecretStr | None = None
    source_timeout_seconds: float = 5
    records_url: str = "http://192.168.31.201:18087"
    records_token: SecretStr | None = None

    crm_url: str = "http://192.168.31.201:18186"
    crm_token: SecretStr | None = None
    crm_write_token: SecretStr | None = None
    plaud_url: str = "http://192.168.31.201:18095"
    plaud_token: SecretStr | None = None
    memos_url: str = "http://192.168.31.201:5230"
    memos_public_url: str = "https://memos-home.172906573.xyz:28443"
    memos_token: SecretStr | None = None

    def secrets(self):
        return [v.get_secret_value() for v in self.__dict__.values() if isinstance(v, SecretStr) and v.get_secret_value()]
