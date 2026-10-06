"""Reuse the maintained health bridge from the same monorepo."""
from pathlib import Path
import runpy
import sys

target = Path(__file__).resolve().parents[3] / "personal-jobs/personal-review-health-source.py"
sys.path.insert(0, str(target.parent))
globals().update(runpy.run_path(str(target), run_name=__name__))
