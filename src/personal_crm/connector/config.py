"""连接器配置。"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class ConnectorConfig:
    """集中保存适配器、过滤、checkpoint 与 Webhook 参数。"""

    chatlog_executable: str = "chatlog-keeper"
    chatlog_expected_sha256: str = ""
    chatlog_scopes_path: str = (
        "~/Library/Application Support/personal-crm/wechat/whitelist-scopes.json"
    )
    chatlog_page_size: int = 200
    chatlog_window_seconds: int = 86400
    chatlog_overlap_seconds: int = 300
    media_enabled: bool = False
    media_queue_path: str = ""
    poll_seconds: float = 60.0
    webhook_url: str = ""
    webhook_token: str = ""
    client_id: str = "legacy"
    account_namespace: str = ""
    checkpoint_path: str = ".personal-crm-wechat-checkpoint.json"
    since: datetime | None = None
    until: datetime | None = None
    timeout: float = 15.0

    @classmethod
    def from_env(cls) -> "ConnectorConfig":
        """从环境变量构建配置，方便 CLI 与 launchd 使用。"""

        # launchd 不会自动读取项目 .env；仅在显式给出文件时加载，且不覆盖进程环境。
        env_file = os.getenv("CRM_ENV_FILE")
        if env_file:
            load_dotenv(Path(env_file).expanduser(), override=False)

        def dt(name):
            """解析可选的 ISO 8601 时间窗口。"""

            value = os.getenv(name)
            return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

        def enabled(name: str, default: bool = False) -> bool:
            """解析显式布尔开关，未知值保持安全默认。"""

            value = os.getenv(name)
            if value is None:
                return default
            return value.strip().lower() in {"1", "true", "yes", "on"}

        return cls(
            chatlog_executable=os.getenv("CHATLOG_EXECUTABLE", cls.chatlog_executable),
            chatlog_expected_sha256=os.getenv("CHATLOG_EXPECTED_SHA256", ""),
            chatlog_scopes_path=os.getenv("CHATLOG_SCOPES", cls.chatlog_scopes_path),
            chatlog_page_size=int(os.getenv("CHATLOG_PAGE_SIZE", "200")),
            chatlog_window_seconds=int(os.getenv("CHATLOG_WINDOW_SECONDS", "86400")),
            chatlog_overlap_seconds=int(os.getenv("CHATLOG_OVERLAP_SECONDS", "300")),
            media_enabled=enabled("WECHAT_MEDIA_ENABLED"),
            media_queue_path=os.getenv("WECHAT_MEDIA_QUEUE", ""),
            poll_seconds=float(os.getenv("CHATLOG_POLL_SECONDS", "60")),
            webhook_url=os.getenv("CRM_WEBHOOK_URL", "").replace(
                "/api/v1/webhooks/wechat", "/api/v1/crm/ingest/wechat"
            ),
            webhook_token=os.getenv("CRM_WEBHOOK_TOKEN", ""),
            client_id=os.getenv("CRM_CLIENT_ID", "legacy"),
            account_namespace=os.getenv("CRM_ACCOUNT_NAMESPACE", ""),
            checkpoint_path=os.getenv("CRM_CHECKPOINT", cls.checkpoint_path),
            since=dt("WECHAT_SINCE"),
            until=dt("WECHAT_UNTIL"),
            timeout=float(os.getenv("CHATLOG_TIMEOUT", "120")),
        )


def as_datetime(value):
    """容错解析适配器返回的 ISO、秒/毫秒时间。"""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, UTC)
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
