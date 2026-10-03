#!/usr/bin/env python3
"""Independent one-shot v2ex entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

TASK = Task('v2ex', DIRECTORY, 'adapter.py', 240,
            frozenset(['V2EX_COOKIE', 'V2EX_PROXY', 'V2EX_USER_AGENT']), browser=False)
if __name__ == "__main__":
    raise SystemExit(run(TASK))
