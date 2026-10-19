#!/usr/bin/env python3
"""Independent WeTalk invocation; scheduling and delivery belong to Hermes."""

import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))

from common.runner import run
from common.task import Task


def configure(parser):
    parser.add_argument("--status", action="store_true", help="Query without signing in")


def command(args):
    return [args.node, str(DIRECTORY / "adapter.cjs"), *(["--status"] if args.status else [])]


TASK = Task(
    "wetalk", DIRECTORY, "adapter.cjs", 120,
    frozenset(["WETALK_CONFIG"]), browser=False, configure=configure, command=command,
)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
