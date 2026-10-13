#!/usr/bin/env python3
"""Deliver non-empty Hub collection reports through the existing notice bot."""

from pathlib import Path
import runpy
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "reports"))
sys.argv = ["dispatch_report.py", "--topic", "hub-collection",
            "--report", str(ROOT / "hub_collection_report.py")]
runpy.run_path(str(ROOT / "reports/common/dispatch_report.py"), run_name="__main__")
