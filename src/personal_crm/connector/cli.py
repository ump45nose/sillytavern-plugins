"""连接器命令行入口。"""

import argparse
import json
import time

from .config import ConnectorConfig
from .sync import WeChatConnector


def _output(result, compact: bool) -> dict:
    """常驻日志只保留数量和状态，避免重复落人物级互动摘要。"""

    if not compact:
        return result.__dict__
    return {
        "batch_id": result.batch_id,
        "interaction_count": len(result.interactions),
        "fact_count": len(result.facts),
        "sent": result.sent,
        "accepted": result.accepted,
        "duplicates": result.duplicates,
        "errors": result.errors,
    }


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
        # watch 日志仅保留批次统计；交互级摘要只在人工单次或 dry-run 时展示。
        print(json.dumps(_output(result, args.watch), ensure_ascii=False, indent=2), flush=True)
        if not args.watch or args.dry_run:
            return 0 if not result.errors else 1
        # 成功窗口（包括已确认的空窗口）快速追赶历史；失败时恢复常规轮询。
        time.sleep(min(config.poll_seconds, 1.0) if result.sent else config.poll_seconds)
