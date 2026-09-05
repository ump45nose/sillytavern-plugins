"""连接器命令行入口。"""

import argparse
import json
import time

from .config import ConnectorConfig
from .sync import WeChatConnector


def main(argv=None):
    """提供 dry-run、单次同步及 launchd 常驻轮询。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    config = ConnectorConfig.from_env()
    connector = WeChatConnector(config)
    while True:
        result = connector.sync_once(args.dry_run)
        # 连接器结果不含原文，可安全写入 launchd 日志用于恢复诊断。
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2), flush=True)
        if not args.watch or args.dry_run:
            return 0 if not result.errors else 1
        # 成功窗口（包括已确认的空窗口）快速追赶历史；失败时恢复常规轮询。
        time.sleep(min(config.poll_seconds, 1.0) if result.sent else config.poll_seconds)
