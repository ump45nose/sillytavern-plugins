#!/usr/bin/env python3
"""Independent one-shot Telegram bot check-in entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent
# The adapter waits up to 600 s for the QR scan; leave room for browser start and close.
LOGIN_TIMEOUT = 900
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

def configure(parser):
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--status", action="store_true")

def validate(parser, args):
    if args.login and (args.status or not sys.stdin.isatty()):
        parser.error("--login requires an interactive terminal and cannot combine with --status")
    if args.login:
        args.timeout = max(args.timeout, LOGIN_TIMEOUT)

def command(args):
    return [args.node, str(DIRECTORY / "adapter.cjs"),
            *(["--login"] if args.login else []), *(["--status"] if args.status else [])]

TASK = Task("telegram", DIRECTORY, "adapter.cjs", 600,
            frozenset(["TELEGRAM_CONFIG", "TELEGRAM_PROXY"]), browser=True,
            configure=configure, command=command, validate=validate)

if __name__ == "__main__":
    raise SystemExit(run(TASK))
