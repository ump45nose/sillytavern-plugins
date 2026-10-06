#!/usr/bin/env python3
"""Hermes wrapper for the repo-managed Favsync cron entrypoint."""

from runpy import run_path
from pathlib import Path

run_path(str(Path(__file__).resolve().parent / "reports/favsync/cron_entrypoint.py"), run_name="__main__")
