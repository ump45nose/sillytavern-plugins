#!/usr/bin/env python3
"""One-account Rainyun task; Hermes owns scheduling and notification."""

import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task


def configure(parser):
    parser.add_argument("--status", action="store_true", help="Read platform state without claiming")


def command(args):
    return [args.python, str(DIRECTORY / "adapter.py"), *(["--status"] if args.status else [])]


TASK = Task("rainyun", DIRECTORY, "adapter.py", 360,
            frozenset(["RAINYUN_CONFIG"]), browser=True,
            configure=configure, command=command)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
