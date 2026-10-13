"""Bounded NAS acceptance; production schedules remain owned by the old stack."""
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess

REPO = Path('/home/yuwk/benefits-automation')
PRIVATE = Path('/vol2/1000/Docker/benefits-automation')
RUNTIME = PRIVATE / 'acceptance-20261003'
EVIDENCE = Path('/home/yuwk/benefits-review/acceptance-20261003')
PYTHON = REPO / '.venv-http/bin/python'
NODE = PRIVATE / 'tools/node'
CACHE = PRIVATE / 'browser-cache'
os.umask(0o077)

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, ensure_ascii=False))
    path.chmod(0o600)

def invoke(platform, env=None, flags=(), timeout=100):
    argv = [str(PYTHON), str(REPO / 'platforms' / platform / 'run.py'),
            '--runtime-root', str(RUNTIME), '--account', 'default',
            '--timezone', 'Asia/Taipei', '--python', str(PYTHON),
            '--node', str(NODE), '--browser-cache', str(CACHE),
            '--timeout', str(timeout), *flags]
    child_env = dict(os.environ)
    child_env.update(env or {})
    run = subprocess.run(argv, env=child_env, capture_output=True, text=True,
                         timeout=timeout + 10)
    try:
        result = json.loads(run.stdout.strip())
    except (ValueError, TypeError):
        result = {'execution_status': 'failed', 'reason': 'launcher_output_invalid'}
    row = {'platform': platform, 'flags': list(flags), 'exit_code': run.returncode,
           'result': result}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row

def main():
    report = []
    # Reuse the first empty-entry smoke output after a preparation-only failure.
    initial = EVIDENCE / 'entry-smoke.json'
    if initial.exists():
        report.extend(json.loads(initial.read_text()))
    else:
        for platform in ['smzdm', 'v2ex', 'aliyun', 'laowang', 'rewards', 'epic']:
            report.append(invoke(platform))
        write(initial, report)

    with sqlite3.connect('file:/vol2/1000/Docker/qinglong/data/db/database.sqlite?mode=ro', uri=True) as db:
        envs = dict(db.execute('SELECT name,value FROM Envs WHERE status=0 AND name IN (?,?)',
                              ('V2EX_COOKIE', 'ALIYUN_COOKIE')))
    smzdm = {}
    for line in Path('/vol2/1000/Docker/qinglong/data/benefits/secrets/smzdm.env').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        parts = shlex.split(value)
        if key.strip() in {'SMZDM_COOKIE', 'SMZDM_SK', 'SMZDM_USER_AGENT_APP'}:
            smzdm[key.strip()] = parts[0] if len(parts) == 1 else value

    # Import only the independently confirmed current-day checkin receipt.
    # Reward and extra-reward state are determined afresh by the new queries.
    old = Path('/vol2/1000/Docker/qinglong/data/benefits/results/smzdm.jsonl')
    last = json.loads(old.read_text().splitlines()[-1])
    if last.get('success') and last.get('business_date') == '2026-10-03':
        write(RUNTIME / 'state/smzdm/default/http-actions.json',
              {'version': 1, 'account': 'default', 'date': last['business_date'],
               'checkin': 'complete', 'reward': 'unknown', 'extra': 'unknown'})

    with sqlite3.connect('file:/vol2/1000/Docker/microsoft-rewards/sessions/sessions.db?mode=ro', uri=True) as db:
        rows = db.execute('SELECT platform,storage_state FROM sessions').fetchall()
    desktop = [r for r in rows if r[0] == 'desktop']
    if len(desktop) != 1:
        raise RuntimeError('single_desktop_session_required')
    write(RUNTIME / 'state/rewards/default/storage-state.json', json.loads(desktop[0][1]))
    # No live production profile is moved or overwritten.
    source = Path('/vol2/1000/Docker/laowang-checkin/browser')
    target = RUNTIME / 'state/laowang/default/browser'
    # Firefox lock links refer to the old process and are not account state.
    shutil.copytree(source, target, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('lock', '.parentlock'))

    report.append(invoke('smzdm', smzdm, ['--execute'], 100))
    report.append(invoke('v2ex', {'V2EX_COOKIE': envs.get('V2EX_COOKIE', ''),
                                'V2EX_PROXY': 'http://192.168.31.201:7890'}, ['--execute'], 100))
    report.append(invoke('aliyun', {'ALIYUN_COOKIE': envs.get('ALIYUN_COOKIE', ''),
                                  'ALIYUN_UPSTREAM_PATH': '/vol2/1000/Docker/qinglong/data/scripts/WillpowerJin_ql-scripts_main/aliyun_dev/daily.py'},
                         ['--execute'], 100))
    report.append(invoke('laowang', {'LAOWANG_PROXY': 'http://192.168.31.201:7890'},
                         ['--execute', '--status'], 90))
    rewards_env = {'REWARDS_ROOT': str(REPO / 'platforms/rewards'),
                   'REWARDS_PROXY': 'http://192.168.31.201:7890'}
    report.append(invoke('rewards', rewards_env, ['--execute', '--mode', 'snapshot'], 90))
    # A missing capabilities manifest and the explicit Epic gate must stay closed.
    report.append(invoke('rewards', rewards_env, ['--execute'], 30))
    report.append(invoke('epic', flags=['--execute'], timeout=30))
    write(EVIDENCE / 'results.json', report)

if __name__ == '__main__':
    main()
