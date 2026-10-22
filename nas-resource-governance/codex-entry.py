#!/usr/bin/python3
"""Put Codex agents in native systemd units; SSH remains outside the budget."""
import os
import sys
import json
from pathlib import Path

REAL = '/home/yuwk/.codexhost/remote/bin/codex'
manifest = json.loads(Path('/home/yuwk/.codexhost/remote/manifest.json').read_text())
for env_name, field in [('CODEXHOST_STOCK_CODEX_PATH', 'stockCodexPath'),
                        ('CODEXHOST_HOST_NODE_PATH', 'nodePath'),
                        ('CODEXHOST_HOST_RUNTIME_PATH', 'hostRuntimePath'),
                        ('CODEXHOST_DATA_DIR', 'dataDirectory')]:
    os.environ.setdefault(env_name, manifest[field])
os.environ.setdefault('CODEXHOST_REMOTE_SSH_MANAGED', '1')
os.environ.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
os.environ['CODEX_INSTALL_DIR'] = os.path.dirname(REAL)
args = sys.argv[1:]
if 'app-server' in args and ('proxy' in args or any(x == 'unix://' or x.startswith(('unix:///', '--listen=unix://')) for x in args)):
    import subprocess
    subprocess.run(['systemctl', '--user', 'start', 'codex-agent.service'], check=True)
    os.execv(REAL, [REAL, *args])
# Standalone CLI workflows get a normal service, within the same total slice.
command = ['/usr/bin/systemd-run', '--user', '--quiet', '--wait', '--collect',
           '--service-type=exec', '--slice=codex.slice',
           '--pty' if os.isatty(0) and os.isatty(1) else '--pipe',
           '--working-directory=' + os.getcwd(),
           '--property=OOMPolicy=kill', '--property=KillMode=control-group',
           '--property=RuntimeMaxSec=7200', '--property=TimeoutStopSec=15']
command += ['--setenv=' + name for name in os.environ]
os.execv(command[0], [*command, '--', REAL, *args])
