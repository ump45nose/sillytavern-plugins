#!/usr/bin/env python3
"""Public one-shot laowang entrypoint."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.runner import run

if __name__ == "__main__":
    raise SystemExit(run("laowang"))
