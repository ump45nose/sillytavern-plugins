"""Personal CRM 运行时配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量读取 NAS 服务配置，不在代码内保存秘密。"""

    database_url: str = "sqlite:///crm.db"
    wechat_webhook_secret: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    mcp_development_no_auth: bool = False
    mcp_proxy_sni_compatibility: bool = False
    public_base_url: str = ""
    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_authorized_usernames: str = ""
    oidc_read_only_usernames: str = ""
    oauth_jwt_signing_key: str = ""
    oauth_storage_encryption_key: str = ""
    oauth_storage_path: str = "/data/oauth"
    # 兼容本机 Agent，以及 GPT、Claude、Grok 官方主域名和所有子域名回调。
    allowed_client_redirect_uris: str = (
        "http://localhost:*,http://127.0.0.1:*,"
        "https://chatgpt.com/*,https://*.chatgpt.com/*,"
        "https://openai.com/*,https://*.openai.com/*,"
        "https://claude.ai/*,https://*.claude.ai/*,"
        "https://anthropic.com/*,https://*.anthropic.com/*,"
        "https://grok.com/*,https://*.grok.com/*,"
        "https://x.ai/*,https://*.x.ai/*,"
        "https://x.com/*,https://*.x.com/*"
    )
    crm_asset_root: str = '/data/crm-assets'
    wechat_interaction_gap_minutes: int = 30
    hub_api_token: str = ''
    hub_viewer_token: str = ''
    # 主动事件必须显式启用并绑定已授权用户，复用现有 /data 持久卷。
    chat_events_enabled: bool = False
    chat_event_owner: str = ""
    chat_event_storage_path: str = "/data/events"
    chat_event_timezone: str = "Asia/Taipei"
    chat_event_time: str = "23:00"
    chat_event_poll_seconds: int = 60
    # Skysight 摘要源只读挂载。
    codex_skylight_path: str = ""
    daily_review_events_enabled: bool = False
    daily_review_event_owner: str = ""
    daily_review_event_storage_path: str = "/data/events/daily-reviews"
    daily_review_event_timezone: str = "Asia/Shanghai"
    daily_review_event_time: str = "23:00"
    daily_review_event_poll_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def oauth_enabled(self) -> bool:
        """仅在公网 URL 与 Authelia OIDC 凭据完整时启用 OAuth。"""

        return bool(
            self.public_base_url
            and self.oidc_discovery_url
            and self.oidc_client_id
            and self.oidc_client_secret
        )

    @staticmethod
    def _csv(value: str) -> set[str]:
        """解析简单逗号列表，避免为少量 ID 引入额外配置格式。"""

        return {item.strip() for item in value.split(",") if item.strip()}

    @property
    def authorized_usernames(self) -> set[str]:
        """允许读取 CRM 的 Authelia 用户名。"""

        return self._csv(self.oidc_authorized_usernames)

    @property
    def read_only_usernames(self) -> set[str]:
        """只能调用读取工具的 Authelia 用户名。"""

        return self._csv(self.oidc_read_only_usernames)

    @property
    def client_redirect_uris(self) -> list[str]:
        """允许 OAuth MCP 客户端使用的回调 URI 模式。"""

        return sorted(self._csv(self.allowed_client_redirect_uris))
