#!/usr/bin/env python3
"""Independent one-shot Olé entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

def configure(parser):
    parser.add_argument("--status", action="store_true")

def command(args):
    return [args.node, str(DIRECTORY / "adapter.cjs"),
            *(["--status"] if args.status else [])]

TASK = Task("ole", DIRECTORY, "adapter.cjs", 240,
            frozenset(["OLE_CONFIG"]), browser=False, configure=configure, command=command)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
