"""Durable backoff; preserve every prior request and resume after interruptions."""
import json
import time
from pathlib import Path

from .core import atomic_bytes, now_iso


def preserve(path, state):
    history = path.parent / (path.stem + '.history')
    history.mkdir(parents=True, exist_ok=True)
    name = f"{time.time_ns()}-{state.get('attempts', 1)}.json"
    atomic_bytes(history / name, json.dumps(state, ensure_ascii=False, indent=2).encode())


def begin(path: Path, identity: dict, stale_seconds=1200, *, artifact_present=True):
    previous = json.loads(path.read_text()) if path.exists() else {}
    same = all(previous.get(k) == v for k, v in identity.items())
    now = time.time()
    if previous and same:
        if previous.get('status') == 'complete' and artifact_present:
            return None
        if previous.get('status') in ('attempted_once', 'running') and now - path.stat().st_mtime < stale_seconds:
            return None
        if float(previous.get('retry_after', 0)) > now:
            return None
    if previous:
        preserve(path, previous)
    state = {**identity, 'status': 'running', 'attempts': int(previous.get('attempts', 1)) + 1 if previous and same else 1,
             'started_at': now_iso()}
    atomic_bytes(path, json.dumps(state, ensure_ascii=False, indent=2).encode())
    return state


def finish(path: Path, state: dict, success: bool, **extra):
    state.update(extra, status='complete' if success else 'failed', completed_at=now_iso())
    state['retry_after'] = 0 if success else time.time() + min(21600, 30 * 2 ** min(state['attempts'] - 1, 10))
    atomic_bytes(path, json.dumps(state, ensure_ascii=False, indent=2).encode())
    return state
