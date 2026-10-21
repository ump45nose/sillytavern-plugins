#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys
target = Path('/home/yuwk/cron/hermes/personal-review-daily-dry-run.py')
sys.path.insert(0, str(target.parent))
globals().update(runpy.run_path(str(target), run_name=__name__))
