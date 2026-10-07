#!/usr/bin/env python3
"""One-time Steam mobile QR login without passwords or logged QR challenges."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

import qrcode

from prepare import ROOT, private_json
from login import NoRedirect
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler


NULL_LOGGING = '''<nlog xmlns="http://www.nlog-project.org/schemas/NLog.xsd"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" throwConfigExceptions="true">
 <targets><target name="discard" xsi:type="Null"/></targets>
 <rules><logger name="*" minlevel="Trace" writeTo="discard"/></rules>
</nlog>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steam-id', required=True)
    parser.add_argument('--region', required=True)
    parser.add_argument('--login-name', required=True)
    parser.add_argument('--compose', type=Path,
                        default=Path('/home/yuwk/code/nas-cron-jobs/steam-asf/compose.yaml'))
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if os.getuid() != 988:
        parser.error('run as the Hermes runtime account')
    if (not re.fullmatch(r'7656119[0-9]{10}', args.steam_id)
            or not re.fullmatch(r'[A-Z]{2}', args.region)
            or not re.fullmatch(r'[A-Za-z0-9_]{1,64}', args.login_name)
            or not 60 <= args.timeout <= 900):
        parser.error('exact account identity, country and bounded timeout required')
    os.umask(0o077)
    private = ROOT / 'private'
    lock = (private / 'qr-login.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('another_qr_login_is_running') from None
    connection_path = private / 'connection.json'
    if connection_path.stat().st_uid != os.getuid() or connection_path.stat().st_mode & 0o077:
        raise RuntimeError('ipc_credential_permissions')
    cfg = json.loads(connection_path.read_text())
    if cfg['ipc_url'] != 'http://127.0.0.1:1242' or cfg['bot'] != 'Main':
        raise RuntimeError('unexpected_ipc_identity')
    settings_path = private / 'steam.json'
    if settings_path.exists():
        existing = json.loads(settings_path.read_text())
        expected = {**cfg, 'steam_id': args.steam_id, 'region': args.region}
        if any(existing.get(k) != expected[k] for k in ('steam_id', 'region', 'bot', 'ipc_url')):
            raise RuntimeError('existing_adapter_identity_differs')
    global_path, bot_path = ROOT / 'config/ASF.json', ROOT / 'config/Main.json'
    original_global = json.loads(global_path.read_text())
    original_bot = json.loads(bot_path.read_text())
    if (original_global.get('Headless') is not True or original_global.get('Debug') is not False
            or original_global.get('IPCPassword') != cfg['ipc_password']
            or original_bot.get('EnableFreePackages') is not False
            or any(original_bot.get(k) for k in ('SteamPassword', 'SteamParentalCode'))):
        raise RuntimeError('unsafe_initial_configuration')
    database_path = ROOT / 'config/Main.db'
    if database_path.exists() and json.loads(database_path.read_text()).get('BackingRefreshToken'):
        raise RuntimeError('existing_session_use_reconnect_instead')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    prefix = '/Api/Bot/Main'

    def request(route, payload=None, post=False):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(cfg['ipc_url'] + route, data=data, method='POST' if post else 'GET',
                      headers={'Authentication': cfg['ipc_password'], 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=10) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
        except HTTPError as error:
            raise RuntimeError('ipc_http_' + str(error.code)) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise RuntimeError('ipc_unavailable') from None
        if len(raw) > 4 * 1024 * 1024:
            raise RuntimeError('ipc_response_limit')
        value = json.loads(raw)
        if value.get('Success') is not True:
            raise RuntimeError('ipc_operation_failed')
        return value.get('Result')

    def bot():
        value = request(prefix)
        if not isinstance(value, dict) or set(value) != {'Main'}:
            raise RuntimeError('unexpected_bot_response')
        return value['Main']

    def ready(timeout=45):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            try:
                return bot()
            except RuntimeError as error:
                if str(error) not in ('ipc_unavailable', 'ipc_http_400'):
                    raise
            time.sleep(1)
        raise RuntimeError('ipc_start_deadline_exceeded')

    def compose(overlay=None):
        command = ['docker', 'compose', '-f', str(args.compose)]
        if overlay is not None:
            command += ['-f', str(overlay)]
        try:
            result = subprocess.run(command + ['up', '-d', '--force-recreate', 'asf'],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('container_recreate_failed') from None
        if result.returncode:
            raise RuntimeError('container_recreate_failed')

    current = bot()
    if current.get('IsConnectedAndLoggedOn'):
        raise RuntimeError('already_logged_on_use_identity_acceptance')
    if current.get('KeepRunning'):
        request(prefix + '/Stop', post=True)
    log_config, overlay = private / 'qr-NLog.config', private / 'qr-compose.json'
    png = private / 'qr-login.png'
    verified = False
    mutated = False

    def interrupted(signum, frame):
        raise RuntimeError('qr_login_interrupted')

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        # ASF's QR implementation logs its URI and writes ASCII QR directly to
        # stdout. Disable both paths before switching off headless mode.
        log_config.write_text(NULL_LOGGING)
        log_config.chmod(0o600)
        private_json(overlay, {'services': {'asf': {
            'entrypoint': ['/bin/sh', '-c', 'umask 077; exec dotnet /asf/ArchiSteamFarm.dll '
                           '--no-restart --no-config-migrate >/dev/null 2>&1'],
            'volumes': [str(log_config) + ':/app/NLog.config:ro'],
        }}})
        mutated = True
        private_json(bot_path, {**original_bot, 'Enabled': False, 'SteamLogin': args.login_name,
                               'EnableFreePackages': False, 'FarmingPreferences': 1,
                               'RemoteCommunication': 0, 'OnlineStatus': 0, 'UseLoginKeys': True})
        private_json(global_path, {**original_global, 'Headless': False})
        compose(overlay)
        current = ready()
        global_config = request('/Api/ASF').get('GlobalConfig', {})
        if (global_config.get('Headless') is not False or global_config.get('Debug') is not False
                or current.get('KeepRunning')
                or current.get('BotConfig', {}).get('EnableFreePackages') is not False):
            raise RuntimeError('qr_configuration_not_applied')
        request(prefix + '/Input', {'Type': 8, 'Value': 'Y'}, post=True)
        request(prefix + '/Start', post=True)
        previous = None
        until = time.monotonic() + args.timeout
        while time.monotonic() < until:
            current = bot()
            if current.get('IsConnectedAndLoggedOn'):
                break
            challenge = current.get('QrChallengeURL')
            if challenge and challenge != previous:
                url = urlsplit(challenge)
                if url.scheme != 'https' or url.netloc != 's.team' or not url.path.startswith('/q/'):
                    raise RuntimeError('unexpected_qr_origin')
                image = qrcode.make(challenge, box_size=8, border=4)
                image.save(png)
                png.chmod(0o600)
                previous = challenge
                print('qr_ready: ' + str(png), flush=True)
            if not current.get('KeepRunning'):
                raise RuntimeError('steam_login_stopped')
            if current.get('RequiredInput') in (1, 2, 3, 4, 5, 7):
                raise RuntimeError('qr_login_requires_other_authorization')
            time.sleep(2)
        else:
            raise RuntimeError('qr_login_deadline_exceeded')
        if str(current.get('s_SteamID', current.get('SteamID'))) != args.steam_id:
            raise RuntimeError('steam_account_mismatch')
        until = time.monotonic() + 30
        while time.monotonic() < until:
            if database_path.exists() and json.loads(database_path.read_text()).get('BackingRefreshToken'):
                break
            time.sleep(1)
        else:
            raise RuntimeError('persistent_session_not_ready')
        # Stop before writing config so the watcher cannot race an active login.
        if bot().get('KeepRunning'):
            request(prefix + '/Stop', post=True)
        private_json(bot_path, {**original_bot, 'Enabled': True, 'SteamLogin': args.login_name,
                               'EnableFreePackages': False, 'FarmingPreferences': 1,
                               'RemoteCommunication': 0, 'OnlineStatus': 0, 'UseLoginKeys': True})
        verified = True
        print('qr_account_verified; restoring normal headless service', flush=True)
    finally:
        try:
            if mutated:
                if not verified:
                    try:
                        if bot().get('KeepRunning'):
                            request(prefix + '/Stop', post=True)
                    except Exception:
                        pass
                    private_json(bot_path, {**original_bot, 'Enabled': False})
                private_json(global_path, original_global)
                compose()
        finally:
            for temporary in (png, overlay, log_config):
                temporary.unlink(missing_ok=True)
    ready()
    until = time.monotonic() + 90
    while time.monotonic() < until:
        current = bot()
        if current.get('IsConnectedAndLoggedOn'):
            if str(current.get('s_SteamID', current.get('SteamID'))) != args.steam_id:
                request(prefix + '/Stop', post=True)
                private_json(bot_path, {**original_bot, 'Enabled': False})
                raise RuntimeError('reconnect_identity_mismatch')
            if not settings_path.exists():
                private_json(settings_path, {**cfg, 'steam_id': args.steam_id, 'region': args.region,
                             'discovery': {'change_number': 0, 'max_packages': 30}})
            print('login_complete; identity and persistent reconnect verified', flush=True)
            return
        time.sleep(2)
    raise RuntimeError('persistent_reconnect_deadline_exceeded')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError):
        # Never print HTTP responses, arbitrary exception text or QR URIs.
        print('QR login stopped; inspect sanitized state before retrying.', file=sys.stderr)
        raise SystemExit(1)
