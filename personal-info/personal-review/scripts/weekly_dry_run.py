#!/usr/bin/env python3
from pathlib import Path
import runpy
import sys
target = Path('/home/yuwk/cron/hermes/personal-review-weekly-dry-run.py')
sys.path.insert(0, str(target.parent))
runpy.run_path(str(target), run_name='__main__')
