#!/usr/bin/env python3
"""Independent Youzan mini-program task; scheduling belongs to the caller."""
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task


def configure(parser):
    parser.add_argument("--status", action="store_true", help="Query without submitting check-in")


def command(args):
    return [args.node, str(DIRECTORY / "adapter.cjs"), *(["--status"] if args.status else [])]


TASK = Task(
    "yingshijufeng", DIRECTORY, "adapter.cjs", 180,
    frozenset(["YINGSHIJUFENG_CONFIG"]), browser=False,
    configure=configure, command=command,
)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
