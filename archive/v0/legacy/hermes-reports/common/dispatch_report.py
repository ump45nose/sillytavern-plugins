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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    config = json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))
    chat_id = str(config["chat_id"])
    thread_id = str(config["threads"][args.topic])
    report = args.report if args.report.is_absolute() else REPO_ROOT / args.report
    result = subprocess.run(
        [sys.executable, str(report)], capture_output=True, text=True, check=False
    )
    message = result.stdout.strip()
    if not message:
        if result.returncode:
            raise SystemExit(f"report process failed with exit code {result.returncode}")
        return 0
    sent = send_report(chat_id, thread_id, message)
    print(f"delivered {sent} message(s) to verified notice-bot topic {args.topic}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
