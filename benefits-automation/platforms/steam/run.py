#!/usr/bin/env python3
"""Offline by default; --execute starts a read-only Steam plan unless --claim."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.runner import run
from common.task import Task


def configure(parser):
    parser.add_argument('--claim', action='store_true', help='Explicitly allow vetted free package submissions')


def validate(parser, args):
    if args.claim and not args.execute:
        parser.error('--claim requires --execute')


def command(args):
    return [args.python, str(Path(__file__).with_name('adapter.py'))] + (['--claim'] if args.claim else [])


if __name__ == '__main__':
    raise SystemExit(run(Task('steam', Path(__file__).resolve().parent, 'adapter.py', 180,
        environment=frozenset({'STEAM_CONFIG'}), configure=configure,
        validate=validate, command=command)))
