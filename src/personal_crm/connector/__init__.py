"""Mac 微信私聊增量采集器。"""

from .config import ConnectorConfig
from .sync import SyncResult, WeChatConnector

__all__ = ["ConnectorConfig", "SyncResult", "WeChatConnector"]
