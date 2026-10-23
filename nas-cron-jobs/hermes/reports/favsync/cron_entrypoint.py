#!/usr/bin/env python3
"""Cron entrypoint for the Favsync exception report."""

from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.argv = ["dispatch_report.py", "--topic", "favsync", "--report", "favsync/daily_report.py"]
runpy.run_path(str(ROOT / "cron_reports/dispatch_report.py"), run_name="__main__")
