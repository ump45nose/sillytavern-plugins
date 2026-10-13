#!/usr/bin/env python3
"""Cron entrypoint for the daily media report."""

from pathlib import Path
from datetime import datetime
import fcntl
import os
import sqlite3
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.dispatch_report import deliver_report
from daily_report import CHECKPOINT, TIMEZONE, load_checkpoint, prepare_report, save_checkpoint


def main():
    CHECKPOINT.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(str(CHECKPOINT) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            report, _issues, checkpoint = prepare_report(datetime.now(TIMEZONE), load_checkpoint())
        except (OSError, sqlite3.Error, ValueError, RuntimeError, TypeError, KeyError):
            deliver_report("media-automation", "- 影视日报：无法读取变更记录")
            return 1
        deliver_report("media-automation", report)
        # Failed Telegram delivery must leave the prior baseline available for retry.
        save_checkpoint(checkpoint)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
