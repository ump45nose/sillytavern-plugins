#!/usr/bin/env python3
"""One-account WorkBuddy task; scheduling and delivery belong to Hermes."""
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task


def configure(parser):
    parser.add_argument("--edition", choices=("cn", "intl"), default="cn")
    parser.add_argument("--status", action="store_true", help="Read only; still requires --execute")


def command(args):
    return [args.python, str(DIRECTORY / "adapter.py"), "--edition", args.edition,
            *(["--status"] if args.status else [])]


TASK = Task("workbuddy", DIRECTORY, "adapter.py", 240,
            frozenset(("WORKBUDDY_CONFIG", "WORKBUDDY_PROXY")),
            configure=configure, command=command)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
