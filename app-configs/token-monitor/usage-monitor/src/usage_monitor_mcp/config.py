from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("/data")
    token_data_file: Path = Path("/sources/token-monitor/devices.json")
    traffic_db: Path = Path("/sources/shellcrash/traffic.sqlite3")
    timezone: str = "Asia/Taipei"
    traffic_timezone: str = "Asia/Shanghai"
    token_stale_after_seconds: int = 600
    token_stats_url: str = ""
    token_secret_file: str = ""
    schedule_hour: int = 23
    schedule_minute: int = 0
    events_enabled: bool = False
    event_subject: str = ""
    http_read_token_file: str = ""

    @classmethod
    def from_env(cls):
        value = cls(
            http_read_token_file=os.getenv("USAGE_HTTP_READ_TOKEN_FILE", ""),
            data_dir=Path(os.getenv("USAGE_DATA_DIR", "/data")),
            token_data_file=Path(os.getenv("TOKEN_MONITOR_DATA_FILE", "/sources/token-monitor/devices.json")),
            traffic_db=Path(os.getenv("SHELLCRASH_TRAFFIC_DB", "/sources/shellcrash/traffic.sqlite3")),
            timezone=os.getenv("USAGE_TIMEZONE", "Asia/Taipei"),
            traffic_timezone=os.getenv("SHELLCRASH_TIMEZONE", "Asia/Shanghai"),
            token_stale_after_seconds=int(os.getenv("TOKEN_MONITOR_STALE_AFTER_SECONDS", "600")),
            token_stats_url=os.getenv("TOKEN_MONITOR_STATS_URL", ""),
            token_secret_file=os.getenv("TOKEN_MONITOR_SECRET_FILE", ""),
            schedule_hour=int(os.getenv("USAGE_DAILY_HOUR", "23")),
            schedule_minute=int(os.getenv("USAGE_DAILY_MINUTE", "0")),
            events_enabled=os.getenv("USAGE_EVENTS_ENABLED", "false").lower() == "true",
            event_subject=os.getenv("USAGE_EVENT_SUBJECT", "").strip(),
        )
        ZoneInfo(value.timezone)
        ZoneInfo(value.traffic_timezone)
        if not 0 <= value.schedule_hour < 24 or not 0 <= value.schedule_minute < 60:
            raise ValueError("日报时间无效")
        if value.token_stale_after_seconds <= 0:
            raise ValueError("设备过期阈值必须为正数")
        if value.events_enabled and not value.event_subject:
            raise ValueError("启用事件必须显式配置 USAGE_EVENT_SUBJECT")
        if bool(value.token_stats_url) != bool(value.token_secret_file):
            raise ValueError("Token Monitor API 地址与秘密文件必须同时配置")
        return value
