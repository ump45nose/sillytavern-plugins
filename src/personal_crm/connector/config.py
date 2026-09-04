"""连接器配置。"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class ConnectorConfig:
    """集中保存适配器、过滤、checkpoint 与 Webhook 参数。"""

    adapter_base_url: str = "http://127.0.0.1:18790"
    adapter_path: str = "/api/messages"
    webhook_url: str = ""
    webhook_token: str = ""
    checkpoint_path: str = ".personal-crm-wechat-checkpoint.json"
    allowed_contacts: set[str] = field(default_factory=set)
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

        contacts = {x.strip() for x in os.getenv("WECHAT_CONTACTS", "").split(",") if x.strip()}
        return cls(
            os.getenv("WELINK_BASE_URL", cls.adapter_base_url),
            os.getenv("WELINK_PATH", cls.adapter_path),
            os.getenv("CRM_WEBHOOK_URL", ""),
            os.getenv("CRM_WEBHOOK_TOKEN", ""),
            os.getenv("CRM_CHECKPOINT", cls.checkpoint_path),
            contacts,
            dt("WECHAT_SINCE"),
            dt("WECHAT_UNTIL"),
            float(os.getenv("WELINK_TIMEOUT", "15")),
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
