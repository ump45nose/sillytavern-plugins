"""数据库初始化、完整性检查和备份命令。"""

from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta
import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from personal_crm.storage import CrmRepository

from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    """执行个人 CRM 运维命令。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init-db", "integrity", "backup", "daily-summary"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("--date", help="daily-summary 的业务日期，格式 YYYY-MM-DD")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="daily-summary 的业务时区")
    args = parser.parse_args(argv)
    repository = CrmRepository(Settings().database_url)
    if args.command == "integrity":
        print(repository.integrity_check())
    elif args.command == "backup":
        if not args.path:
            parser.error("backup requires path")
        print(repository.backup(args.path))
    elif args.command == "daily-summary":
        if not args.date:
            parser.error("daily-summary requires --date")
        try:
            business_day = datetime.strptime(args.date, "%Y-%m-%d").date()
            zone = ZoneInfo(args.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            parser.error(f"invalid date or timezone: {error}")
        # CLI 与 MCP 使用相同半开业务日窗口，输出也只包含无正文聚合。
        start = datetime.combine(business_day, time.min, zone)
        summary = repository.daily_summary(start, start + timedelta(days=1))
        print(json.dumps({"date": args.date, "timezone": args.timezone, **summary}, ensure_ascii=False))
    else:
        print("initialized")
    return 0
