#!/usr/bin/env python3
"""Run one report and deliver non-empty output through the notice bot."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from common.telegram_notice import send_report


TOPIC_CONFIG = Path("/home/hermes/.hermes/profiles/lingjun/cron/notice_topics.json")


def deliver_report(topic: str, message: str) -> int:
    if not message.strip():
        return 0
    config = json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))
    sent = send_report(str(config["chat_id"]), str(config["threads"][topic]), message)
    print(f"delivered {sent} message(s) to verified notice-bot topic {topic}")
    return sent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    report = args.report if args.report.is_absolute() else REPO_ROOT / args.report
    result = subprocess.run(
        [sys.executable, str(report)], capture_output=True, text=True, check=False
    )
    message = result.stdout.strip()
    if not message:
        if result.returncode:
            raise SystemExit(f"report process failed with exit code {result.returncode}")
        return 0
    deliver_report(args.topic, message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
