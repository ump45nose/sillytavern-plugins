"""连接器命令行入口。"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .checkpoint import load
from .config import ConnectorConfig, as_datetime
from .sync import WeChatConnector


def _output(result, compact: bool) -> dict:
    """常驻日志只保留数量和状态，避免重复落人物级互动摘要。"""

    if not compact:
        return result.__dict__
    return {
        "message_count": len(result.messages),
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
    os.environ["PATH"] = (
        str(Path(config.chatlog_executable).parent) + os.pathsep + os.environ.get("PATH", "")
    )
    connector = WeChatConnector(config)

    def media_run():
        from .media import MediaQueue

        with httpx.Client(timeout=max(config.timeout, 300)) as client:
            return MediaQueue(config).run_once(client)

    # 原文件读取/上传可能慢于文字轮询；仅允许一个媒体 worker。
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = None
        while True:
            result = connector.sync_once(args.dry_run)
            print(json.dumps(_output(result, True), ensure_ascii=False, indent=2), flush=True)
            if config.media_enabled and not args.dry_run:
                if future is not None and future.done():
                    try:
                        media_status = future.result()
                    except Exception:
                        media_status = {"error": "media_worker_failed"}
                    print(json.dumps({"media": media_status}), flush=True)
                    future = None
                if future is None:
                    future = executor.submit(media_run)
            if not args.watch or args.dry_run:
                if future is not None:
                    try:
                        print(json.dumps({"media": future.result()}), flush=True)
                    except Exception:
                        print('{"media":{"error":"media_worker_failed"}}', flush=True)
                return 0 if not result.errors else 1
            watermark = (
                as_datetime(load(config.checkpoint_path).get("last_synced_at"))
                if result.sent
                else None
            )
            behind = (
                watermark is not None
                and (datetime.now(UTC) - watermark).total_seconds()
                > config.chatlog_overlap_seconds + 60
            )
            time.sleep(
                min(config.poll_seconds, 1.0) if result.sent and behind else config.poll_seconds
            )
