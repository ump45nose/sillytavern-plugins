"""连接器命令行入口。"""

import argparse
import json

from .config import ConnectorConfig
from .sync import WeChatConnector


def main(argv=None):
    """提供 dry-run 与单次同步命令。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = WeChatConnector(ConnectorConfig.from_env()).sync_once(args.dry_run)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0 if not result.errors else 1
