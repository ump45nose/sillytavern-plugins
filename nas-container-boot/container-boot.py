#!/usr/bin/env python3
"""Start the existing NAS containers in dependency order after Docker is ready."""

import argparse
import datetime as dt
import fcntl
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

ORDER = Path('/home/yuwk/cron/scripts/container-boot-order.txt')
IGNORE = Path('/home/yuwk/cron/scripts/container-boot-ignore.txt')
LOCK = '/tmp/container-boot.lock'


def log(message):
    print(f'{dt.datetime.now().astimezone().isoformat(timespec="seconds")} {message}', flush=True)


def run(*args, timeout=15):
    try:
        return subprocess.run(args, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def inspect(name):
    result = run('docker', 'inspect', name)
    if result is None or result.returncode:
        return None
    return json.loads(result.stdout)[0]


def load_order():
    entries = []
    seen = set()
    for number, line in enumerate(ORDER.read_text().splitlines(), 1):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2 or not parts[0].isdigit():
            raise ValueError(f'{ORDER}:{number}: expected stage container [dependencies]')
        stage, name, *dependencies = parts
        if name in seen:
            raise ValueError(f'{ORDER}:{number}: duplicate {name}')
        if any(dep not in seen for dep in dependencies):
            raise ValueError(f'{ORDER}:{number}: dependency must appear earlier: {dependencies}')
        if entries and int(stage) < entries[-1][0]:
            raise ValueError(f'{ORDER}:{number}: stages must increase')
        entries.append((int(stage), name, dependencies))
        seen.add(name)
    return entries


def open_lock():
    # flock works on a read descriptor. Avoid O_CREAT for existing /tmp files:
    # Linux protected_regular can otherwise reject a different runtime owner.
    try:
        return open(LOCK, 'r')
    except FileNotFoundError:
        try:
            fd = os.open(LOCK, os.O_RDONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return open(LOCK, 'r')
        os.fchmod(fd, 0o644)
        return os.fdopen(fd, 'r')


def tailnet_ready():
    result = run('ip', '-o', '-4', 'addr', 'show', 'dev', 'tailscale0', timeout=5)
    return bool(result and result.returncode == 0 and
                any(' inet ' in line for line in result.stdout.splitlines()))


def ready(name):
    data = inspect(name)
    if not data or data['State']['Status'] != 'running':
        return False
    health = data['State'].get('Health')
    if health and health['Status'] != 'healthy':
        return False
    if name == 'mariadb':
        result = run('docker', 'exec', name, 'healthcheck.sh', '--connect', '--innodb_initialized', timeout=5)
        return bool(result and result.returncode == 0)
    if name == 'redis':
        result = run('docker', 'exec', name, 'sh', '-c',
                     'redis-cli ping 2>&1 | grep -Eq "^(PONG|NOAUTH)"', timeout=5)
        return bool(result and result.returncode == 0)
    if name == 'tailscale':
        return tailnet_ready()
    if name == 'nginx-proxy-manager':
        try:
            config_path = Path(os.environ.get('HERMES_CRON_CONFIG', '/home/yuwk/cron/env/hermes.local.json'))
            config = json.loads(config_path.read_text()) if config_path.exists() else {}
            url = os.environ.get('NAS_NPM_HEALTH_URL') or config.get('npm_health_url', 'http://127.0.0.1:28081/')
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url, timeout=3) as response:
                return response.status < 500
        except (OSError, urllib.error.URLError):
            return False
    return True


def wait_ready(name, seconds=120):
    # Tailscale can acquire its address late; leave the boot runner alive for it.
    started = time.monotonic()
    last_notice = -1
    while True:
        if ready(name):
            return True
        elapsed = int(time.monotonic() - started)
        if name != 'tailscale' and elapsed >= seconds:
            log(f'ERROR timeout waiting for {name} readiness')
            return False
        if elapsed // 60 != last_notice:
            log(f'waiting for {name} readiness ({elapsed}s)')
            last_notice = elapsed // 60
        time.sleep(5)


def load_ignore():
    if not IGNORE.exists():
        return []
    return [line.split('#', 1)[0].strip() for line in IGNORE.read_text().splitlines()
            if line.split('#', 1)[0].strip()]


def check(entries):
    result = run('docker', 'ps', '-a', '--format', '{{json .}}')
    if not result or result.returncode:
        log('ERROR docker inventory unavailable')
        return 1
    containers = {row['Names']: row for row in map(json.loads, result.stdout.splitlines())}
    planned = {name for _, name, _ in entries}
    missing = sorted(planned - containers.keys())
    ignore = load_ignore()
    ignored_active = sorted(name for name, row in containers.items()
                            if row['State'] == 'running' and name not in planned
                            and any(fnmatch.fnmatchcase(name, pattern) for pattern in ignore))
    active_unplanned = sorted(name for name, row in containers.items()
                              if row['State'] == 'running' and name not in planned
                              and name not in ignored_active)
    stopped_planned = sorted(name for name in planned & containers.keys()
                             if containers[name]['State'] != 'running')
    counts = {}
    for stage, _, _ in entries:
        counts[stage] = counts.get(stage, 0) + 1
    log(f'plan: {len(entries)} containers; stage counts {counts}')
    log(f'missing={missing} active_unplanned={active_unplanned} ignored_active={ignored_active} stopped_planned={stopped_planned}')
    return int(bool(missing or active_unplanned or stopped_planned))


def start(entries):
    failures = []
    previous_stage = None
    for stage, name, dependencies in entries:
        if stage != previous_stage:
            log(f'stage {stage} begin')
            previous_stage = stage
        data = inspect(name)
        if not data:
            log(f'ERROR missing container {name}; preserve configuration and retry later')
            failures.append(name)
            continue
        if any(not wait_ready(dep) for dep in dependencies):
            log(f'ERROR skipped {name}: prerequisite unavailable')
            failures.append(name)
            continue
        if data['State']['Status'] != 'running':
            result = run('docker', 'start', name, timeout=90)
            if not result or result.returncode:
                log(f'ERROR start {name}: {(result.stderr if result else "timeout").strip()[:300]}')
                failures.append(name)
                continue
            log(f'started {name}')
        else:
            log(f'already running {name}')
        # Database and gateway consumers need their prerequisites ready, not
        # just a successful docker start response.
        if (stage <= 20 and name != 'tailscale') or name in ('memos', 'mailflow-backend', 'resume-builder-python-ai-backend',
                                   'subboost-app-1', 'qinglong'):
            if not wait_ready(name):
                failures.append(name)
    log(f'boot pass complete; failures={failures}')
    return int(bool(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='read-only inventory and plan check')
    args = parser.parse_args()
    entries = load_order()
    if args.check:
        return check(entries)
    with open_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for attempt in range(60):
            result = run('docker', 'info', timeout=5)
            if result and result.returncode == 0 and ORDER.exists():
                break
            log(f'waiting for Docker and boot order ({attempt + 1}/60)')
            time.sleep(5)
        else:
            log('ERROR Docker or boot order unavailable')
            return 1
        return start(entries)


if __name__ == '__main__':
    sys.exit(main())
