#!/usr/bin/env python3
"""Cron entrypoint for the benefits exception report."""

from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.argv = [
    "dispatch_report.py", "--topic", "benefits-automation",
    "--report", "benefits-automation/daily_report.py",
]
runpy.run_path(str(ROOT / "common/dispatch_report.py"), run_name="__main__")
