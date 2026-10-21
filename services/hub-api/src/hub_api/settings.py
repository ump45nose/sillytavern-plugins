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

    token_url: str = "http://192.168.31.201:17321"
    token_secret: SecretStr | None = None
    usage_url: str = "http://192.168.31.201:18103"
    usage_token: SecretStr | None = None

    media_signing_key: SecretStr | None = None
    emby_url: str = "http://192.168.31.201:28096"
    emby_public_url: str = "https://emby-home.172906573.xyz:28443"
    emby_token: SecretStr | None = None
    emby_user_id: str = ""
    navidrome_url: str = "http://192.168.31.201:14533"
    navidrome_public_url: str = "https://navidrome-home.172906573.xyz:28443"
    navidrome_user: str = ""
    navidrome_password: SecretStr | None = None
    moviepilot_url: str = "http://moviepilot:3001"
    moviepilot_public_url: str = "https://moviepilot-home.172906573.xyz:28443"
    moviepilot_token: SecretStr | None = None
    qbittorrent_url: str = "http://192.168.31.201:18080"
    qbittorrent_public_url: str = "http://192.168.31.201:18080"
    qbittorrent_user: str | None = None
    qbittorrent_password: SecretStr | None = None

    github_token: SecretStr | None = None
    github_timeout_seconds: float = 15

    public_url: str = "https://hub-home.172906573.xyz:28443"
    oidc_issuer: str | None = None
    oidc_client_id: str = "personal-hub"
    oidc_client_secret: SecretStr | None = None
    allowed_subjects: list[str] = []

    def secrets(self):
        return [v.get_secret_value() for v in self.__dict__.values() if isinstance(v, SecretStr) and v.get_secret_value()]
