import sys
from pathlib import Path
sys.path.insert(0,'/home/yuwk/benefits-automation')
from common.task import Task
from common.runner import run
script=Path('/home/yuwk/benefits-review/implementation-20261003/bing-challenge-probe.cjs')
raise SystemExit(run(Task('rewards',script.parent,script.name,120,frozenset({'REWARDS_PROXY'}),browser=True)))
