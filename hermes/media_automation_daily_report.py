#!/usr/bin/env python3
"""Hermes entrypoint for the repository-managed media report."""

from runpy import run_path
from pathlib import Path

run_path(str(Path(__file__).resolve().parent / "reports/media-automation/daily_report.py"), run_name="__main__")
