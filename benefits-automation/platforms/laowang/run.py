#!/usr/bin/env python3
"""Independent one-shot laowang entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

def configure(parser):
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--status", action="store_true")
def validate(parser, args):
    if args.login and (args.status or not sys.stdin.isatty()):
        parser.error("--login requires an interactive terminal and cannot combine with --status")
def command(args):
    return [args.node, str(DIRECTORY / "adapter.cjs"),
            *(["--login"] if args.login else []), *(["--status"] if args.status else [])]

TASK = Task('laowang', DIRECTORY, 'adapter.cjs', 360,
            frozenset(['LAOWANG_PROXY', 'COOKIECLOUD_CONFIG']), browser=True, configure=configure, command=command, validate=validate)
if __name__ == "__main__":
    raise SystemExit(run(TASK))
