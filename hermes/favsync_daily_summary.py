#!/usr/bin/env python3
"""Hermes entrypoint for the repository-managed Favsync alert."""

from runpy import run_path
from pathlib import Path

run_path(str(Path(__file__).resolve().parent / "reports/favsync/daily_report.py"), run_name="__main__")
