#!/usr/bin/env python3
"""Read-only Yanxuan points entrypoint; no sign-in run.py until verified."""

import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))

from common.runner import run
from common.task import Task

TASK = Task(
    "yanxuan", DIRECTORY, "adapter.py", 120,
    frozenset(["YANXUAN_COOKIE", "YANXUAN_USER_AGENT", "YANXUAN_PROXY"]),
    browser=False,
)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
