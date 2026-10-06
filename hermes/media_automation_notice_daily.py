#!/usr/bin/env python3
"""Hermes wrapper for the repo-managed media cron entrypoint."""

from runpy import run_path
from pathlib import Path

run_path(str(Path(__file__).resolve().parent / "reports/media-automation/cron_entrypoint.py"), run_name="__main__")
