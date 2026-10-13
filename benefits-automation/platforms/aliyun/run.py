#!/usr/bin/env python3
"""Independent one-shot aliyun entry; scheduling and delivery belong to the caller."""
import sys
from pathlib import Path
DIRECTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(DIRECTORY.parents[1]))
from common.runner import run
from common.task import Task

TASK = Task('aliyun', DIRECTORY, 'adapter.py', 480,
            frozenset(['ALIYUN_COOKIE', 'ALIYUN_UPSTREAM_PATH', 'ALIYUN_PROXY', 'COOKIECLOUD_CONFIG']), browser=False)
if __name__ == "__main__":
    raise SystemExit(run(TASK))
