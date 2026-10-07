#!/usr/bin/env python3
"""Prepare private ASF data, preserving existing IPC identity and bot state."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import zipfile

ROOT = Path('/vol2/1000/Docker/benefits-automation/steam-asf')
PLUGIN_SHA256 = '949a7be69d8c03bb85f1c8e8d169eea37c1c363166227237110e62e9c66e1961'


def private_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.steam-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-zip', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if os.getuid() != 988:
        parser.error('run as the Hermes runtime account')
    for name in ('config', 'plugins', 'logs', 'private'):
        path = ROOT / name
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
            parser.error('private data directory ownership or permissions differ')
    raw = args.plugin_zip.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PLUGIN_SHA256:
        parser.error('plugin checksum mismatch')
    with zipfile.ZipFile(args.plugin_zip) as archive:
        for entry in archive.infolist():
            target = (ROOT / 'plugins' / entry.filename).resolve()
            if ROOT / 'plugins' not in target.parents:
                parser.error('invalid plugin archive path')
            if entry.is_dir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
                target.chmod(0o600)
    global_path = ROOT / 'config/ASF.json'
    connection_path = ROOT / 'private/connection.json'
    if global_path.exists() != connection_path.exists():
        parser.error('existing IPC configuration is incomplete; review before repair')
    if not global_path.exists():
        password = secrets.token_urlsafe(48)
        private_json(global_path, {
            'IPC': True, 'IPCPassword': password, 'Headless': True,
            'Debug': False, 'UpdatePeriod': 0, 'UpdateChannel': 0,
        })
        private_json(connection_path, {
            'ipc_url': 'http://127.0.0.1:1242', 'ipc_password': password, 'bot': 'Main',
        })
    private_json(ROOT / 'config/IPC.config', {
        'Kestrel': {'Endpoints': {'HTTP': {'Url': 'http://*:1242'}}},
    })
    if not (ROOT / 'config/Main.json').exists():
        private_json(ROOT / 'config/Main.json', {
            'Enabled': False, 'FarmingPreferences': 1, 'OnlineStatus': 0,
            'RemoteCommunication': 0, 'EnableFreePackages': False,
            'UseLoginKeys': True,
        })
    print('Private data prepared; bot disabled; no Steam credentials stored.')


if __name__ == '__main__':
    main()
