"""Personal CRM 运行时配置。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量读取 NAS 服务配置，不在代码内保存秘密。"""

    database_url: str = "sqlite:///crm.db"
    wechat_webhook_secret: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    public_base_url: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    github_allowed_user_ids: str = ""
    github_read_only_user_ids: str = ""
    oauth_jwt_signing_key: str = ""
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
    reminder_scheduler_enabled: bool = True
    reminder_poll_seconds: int = 3600

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    @property
    def oauth_enabled(self) -> bool:
        """仅在公网 URL 与 GitHub 凭据完整时启用 OAuth。"""

        return bool(self.public_base_url and self.github_client_id and self.github_client_secret)

    @staticmethod
    def _csv(value: str) -> set[str]:
        """解析简单逗号列表，避免为少量 ID 引入额外配置格式。"""

        return {item.strip() for item in value.split(",") if item.strip()}

    @property
    def allowed_user_ids(self) -> set[str]:
        """允许读取 CRM 的 GitHub 数字用户 ID。"""

        return self._csv(self.github_allowed_user_ids)

    @property
    def read_only_user_ids(self) -> set[str]:
        """只能调用读取工具的 GitHub 数字用户 ID。"""

        return self._csv(self.github_read_only_user_ids)

    @property
    def client_redirect_uris(self) -> list[str]:
        """允许 OAuth MCP 客户端使用的回调 URI 模式。"""

        return sorted(self._csv(self.allowed_client_redirect_uris))
