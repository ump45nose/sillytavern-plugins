#!/usr/bin/env python3
"""Compatibility entrypoint for the Personal Review business collector."""
from pathlib import Path
import os
import runpy
import sys

APP_ROOT = Path(os.environ.get("REVIEW_APP_ROOT", "/vol2/1000/Docker/personal-review"))
sys.path.insert(0, str(APP_ROOT))
if __name__ == "__main__":
    runpy.run_module("review.sources.google_input", run_name="__main__")
