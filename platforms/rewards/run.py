#!/usr/bin/env python3
"""Independent one-shot rewards entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

MODES = {"full": "full.cjs", "activities": "activities.cjs", "snapshot": "snapshot.cjs",
         "extra": "extra.cjs", "desktop-search": "search.cjs", "mobile-search": "search.cjs",
         "punchcards": "punchcards.cjs"}
def configure(parser):
    parser.add_argument("--mode", choices=MODES, default="full")
def command(args):
    return [args.node, str(DIRECTORY / MODES[args.mode]),
            *(["--mobile"] if args.mode == "mobile-search" else [])]

TASK = Task('rewards', DIRECTORY, 'full.cjs', 7500,
            frozenset(['REWARDS_ROOT', 'REWARDS_PROXY']), browser=True, configure=configure, command=command, result_partition=lambda args: args.mode)
if __name__ == "__main__":
    raise SystemExit(run(TASK))
