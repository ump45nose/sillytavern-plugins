#!/usr/bin/env python3
"""One-account GLaDOS entry; scheduling and notification belong to Hermes."""

import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task


def configure(parser):
    parser.add_argument("--status", action="store_true", help="Read only; requires --execute")


def command(args):
    return [args.python, str(DIRECTORY / "adapter.py"), "--timezone", args.timezone,
            *(["--status"] if args.status else [])]


TASK = Task(
    "glados", DIRECTORY, "adapter.py", 180,
    frozenset({"GLADOS_ORIGIN", "GLADOS_COOKIE", "GLADOS_USER_AGENT", "GLADOS_TOKEN",
               "GLADOS_PROXY", "COOKIECLOUD_CONFIG"}),
    browser=False, configure=configure, command=command,
)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
