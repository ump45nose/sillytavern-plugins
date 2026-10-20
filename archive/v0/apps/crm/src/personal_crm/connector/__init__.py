"""Mac WeChat/WeLink 只读连接器。"""

from .config import ConnectorConfig
from .sync import SyncResult, WeChatConnector

__all__ = ["ConnectorConfig", "SyncResult", "WeChatConnector"]
