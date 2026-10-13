#!/usr/bin/env python3
"""Restore and supervise the existing Grok Bot Tailnet identity and chat adapter."""
import argparse
import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/home/box/cli-config/grokbot')
PROXY = Path('/home/box/cursor-proxy')
STATE = ROOT / 'tailscaled.state'
RUNTIME_STATE = Path('/var/lib/tailscale/tailscaled.state')
RUNTIME_BIN = Path('/usr/local/libexec/grokbot')
SOCKET = '/var/run/tailscale/tailscaled.sock'
BOOT = Path('/usr/local/bin/start-sand-box')
MARKER = '# Grok Bot Tailnet recovery (app-configs/grokbot)'
STOP = False


def run(args, timeout=15, check=True):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if check and result.returncode:
        # Commands may encounter private state. Keep diagnostics free of output.
        raise RuntimeError(f'{Path(args[0]).name} failed with exit {result.returncode}')
    return result


def atomic_private(path, data):
    temp = path.with_name(path.name + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def cmdline(pid):
    try:
        return Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    except OSError:
        return []


def find_process(kind):
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        args = cmdline(entry.name)
        if not args:
            continue
        if kind == 'tailscale' and Path(os.fsdecode(args[0])).name == 'tailscaled' and any(x.startswith(b'--state=') for x in args):
            return int(entry.name), args
        if kind == 'proxy' and os.fsencode(str(PROXY / 'proxy.js')) in args:
            return int(entry.name), args
    return None, []


def sudo(args, **kwargs):
    return run(['sudo', '-n', *args], **kwargs)


def cli(*args, check=True):
    return sudo([str(ROOT / 'bin/tailscale'), '--socket=' + SOCKET, *args], timeout=45, check=check)


def snapshot_identity():
    _, args = find_process('tailscale')
    source = next((os.fsdecode(x[8:]) for x in args if x.startswith(b'--state=')), None)
    if source:
        if Path(source) == STATE:
            sudo(['chown', f'{os.getuid()}:{os.getgid()}', str(STATE)])
            os.chmod(STATE, 0o600)
        else:
            contents = sudo(['cat', source]).stdout
            json.loads(contents)  # Reject incomplete snapshots without exposing keys.
            if not STATE.exists() or STATE.read_bytes() != contents:
                atomic_private(STATE, contents)
    if not STATE.is_file() or STATE.stat().st_size == 0:
        raise RuntimeError('No saved Tailscale identity; interactive authorization is required')
    keys = sudo(['tar', '-C', '/var/lib/tailscale', '-cf', '-', 'ssh'], check=False)
    if keys.returncode == 0:
        target = ROOT / 'ssh-host-keys.tar'
        if not target.exists() or target.read_bytes() != keys.stdout:
            atomic_private(target, keys.stdout)


def install_boot_hook():
    text = sudo(['cat', str(BOOT)]).stdout.decode()
    if MARKER in text:
        return
    anchor = '\ncli_auth_boot\napply_box_timezone\n'
    if text.count(anchor) != 1:
        raise RuntimeError('Platform startup script changed; boot hook needs review')
    hook = f'''\n{MARKER}
if [ -f {ROOT}/recover.py ]; then
    /usr/sbin/runuser -u box -- /usr/bin/python3 {ROOT}/recover.py start \\
        >>/tmp/grokbot-recovery-boot.log 2>&1 || true
fi
'''
    patched = text.replace(anchor, hook + anchor)
    temporary = ROOT / 'start-sand-box.patched'
    temporary.write_text(patched)
    try:
        run(['bash', '-n', str(temporary)])
        backup = ROOT / 'start-sand-box.original'
        if not backup.exists():
            backup.write_text(text)
        sudo(['cp', str(temporary), str(BOOT)])
        sudo(['chmod', '755', str(BOOT)])
    finally:
        temporary.unlink(missing_ok=True)


def prepare():
    ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(ROOT, 0o700)
    binary_dir = ROOT / 'bin'
    binary_dir.mkdir(mode=0o700, exist_ok=True)
    for name in ['tailscale', 'tailscaled']:
        target = binary_dir / name
        if not target.exists():
            source = shutil.which(name) or ('/usr/sbin/' + name)
            if not Path(source).is_file():
                raise RuntimeError(f'Missing retained {name} binary')
            sudo(['cp', source, str(target)])
            sudo(['chown', f'{os.getuid()}:{os.getgid()}', str(target)])
        target.chmod(0o700)
    sudo(['mkdir', '-p', str(RUNTIME_BIN)])
    sudo(['chmod', '755', str(RUNTIME_BIN)])
    for name in ['tailscale', 'tailscaled']:
        if sudo(['cmp', '-s', str(binary_dir / name), str(RUNTIME_BIN / name)], check=False).returncode:
            sudo(['install', '-o', 'root', '-g', 'root', '-m', '755', str(binary_dir / name), str(RUNTIME_BIN / name)])
    snapshot_identity()
    if not (PROXY / 'config.json').is_file() or not (PROXY / 'proxy.js').is_file():
        raise RuntimeError('Saved chat adapter configuration is missing')
    install_boot_hook()


def proxy_health():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:1341/healthz', timeout=2) as response:
            return json.load(response).get('ok') is True
    except (OSError, ValueError):
        return False


def status():
    try:
        result = cli('status', '--json', check=False)
        state = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        state = {}
    healthy = state.get('BackendState') == 'Running' and proxy_health()
    pid = None
    try:
        candidate = int((ROOT / 'supervisor.pid').read_text())
        if os.fsencode(str(ROOT / 'recover.py')) in cmdline(candidate):
            pid = candidate
    except (OSError, ValueError):
        pass
    return {
        'ok': healthy and pid is not None,
        'supervisorPid': pid,
        'tailscaleState': state.get('BackendState', 'Unavailable'),
        'tailscaleIPs': state.get('Self', {}).get('TailscaleIPs', []),
        'proxyHealthy': proxy_health(),
        'savedIdentity': STATE.is_file(),
        'bootHook': BOOT.is_file() and MARKER in BOOT.read_text(),
    }


def start():
    current = status()
    if current['supervisorPid'] is not None:
        revision = ROOT / 'supervisor.sha256'
        expected = hashlib.sha256((ROOT / 'recover.py').read_bytes()).hexdigest()
        if revision.is_file() and revision.read_text() == expected:
            return current
        pid = current['supervisorPid']
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not cmdline(pid):
                break
            time.sleep(0.5)
        else:
            os.kill(pid, signal.SIGKILL)
    with open(ROOT / 'supervisor-launch.log', 'ab') as log:
        subprocess.Popen(
            [sys.executable, str(ROOT / 'recover.py'), 'daemon'],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            start_new_session=True,
        )
    for _ in range(10):
        time.sleep(0.5)
        current = status()
        if current['supervisorPid'] is not None:
            return current
    raise RuntimeError('Recovery supervisor did not start')


def daemon():
    global STOP
    lock = open(ROOT / 'supervisor.lock', 'a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    (ROOT / 'supervisor.pid').write_text(str(os.getpid()))
    (ROOT / 'supervisor.sha256').write_text(hashlib.sha256((ROOT / 'recover.py').read_bytes()).hexdigest())
    handler = RotatingFileHandler(ROOT / 'supervisor.log', maxBytes=1048576, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger = logging.getLogger('grokbot-recovery')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    for sig in [signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, lambda *_: globals().__setitem__('STOP', True))
    children = []
    serve_installed = False
    last_failure = None
    try:
        while not STOP:
            for child in children[:]:
                if child.poll() is not None:
                    children.remove(child)
            try:
                snapshot_identity()
                ts_pid, _ = find_process('tailscale')
                if ts_pid is None:
                    sudo(['mkdir', '-p', '/var/run/tailscale', str(RUNTIME_STATE.parent)])
                    sudo(['chmod', '700', str(RUNTIME_STATE.parent)])
                    sudo(['install', '-o', 'root', '-g', 'root', '-m', '600', str(STATE), str(RUNTIME_STATE)])
                    if (ROOT / 'ssh-host-keys.tar').is_file():
                        sudo(['tar', '-C', str(RUNTIME_STATE.parent), '-xf', str(ROOT / 'ssh-host-keys.tar')])
                    with open(ROOT / 'tailscaled.log', 'ab') as log:
                        child = subprocess.Popen([
                            'sudo', '-n', str(RUNTIME_BIN / 'tailscaled'),
                            '--tun=userspace-networking', '--state=' + str(RUNTIME_STATE),
                            '--statedir=' + str(RUNTIME_STATE.parent),
                            '--socket=' + SOCKET,
                        ], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                    children.append(child)
                    serve_installed = False
                    logger.info('Started tailscaled from the saved identity')
                    time.sleep(2)
                ts = json.loads(cli('status', '--json').stdout)
                if ts.get('BackendState') != 'Running':
                    raise RuntimeError('Tailscale is not logged in; manual authorization is required')
                if not serve_installed:
                    cli('set', '--ssh')
                    cli('serve', '--bg', '--yes', '--tcp=1341', 'tcp://127.0.0.1:1341')
                    serve_installed = True
                proxy_pid, _ = find_process('proxy')
                if proxy_pid is None:
                    node = '/exec-daemon/node' if Path('/exec-daemon/node').is_file() else shutil.which('node')
                    if not node:
                        raise RuntimeError('Node runtime unavailable')
                    with open(PROXY / 'cursor-proxy.log', 'ab') as log:
                        child = subprocess.Popen([node, str(PROXY / 'proxy.js')],
                                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                                 start_new_session=True)
                    children.append(child)
                    (PROXY / 'proxy.pid').write_text(str(child.pid))
                    logger.info('Started the chat adapter')
                snapshot_identity()
                if last_failure:
                    logger.info('Recovery succeeded')
                last_failure = None
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                message = str(error)
                if message != last_failure:
                    logger.error('%s', message)
                    last_failure = message
            for _ in range(10):
                if STOP:
                    break
                time.sleep(0.5)
    finally:
        (ROOT / 'supervisor.pid').unlink(missing_ok=True)
        # Leave healthy services alive when only the supervisor is restarted.
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', nargs='?', default='ensure', choices=['ensure', 'start', 'status', 'daemon'])
    command = parser.parse_args().command
    if command == 'daemon':
        daemon()
        return
    if command == 'ensure':
        prepare()
    result = status() if command == 'status' else start()
    print(json.dumps(result, ensure_ascii=False))
    if command == 'status' and not result['ok']:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok': False, 'error': str(error)}))
        sys.exit(1)
