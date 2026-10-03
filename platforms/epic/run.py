#!/usr/bin/env python3
"""Independent one-shot epic entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

TASK = Task('epic', DIRECTORY, 'adapter.py', 1300,
            frozenset(['EPIC_CONFIG']), browser=True)
if __name__ == "__main__":
    raise SystemExit(run(TASK))
