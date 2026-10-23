#!/usr/bin/env python3
"""Run the business collector from this application checkout."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if __name__ == "__main__":
    runpy.run_module("review.sources.google_input", run_name="__main__")
