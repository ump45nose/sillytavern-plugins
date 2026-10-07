#!/usr/bin/env python3
"""Human-run terminal login: transient IPC inputs, never password/code files."""
import argparse
import atexit
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import sys
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from prepare import ROOT, private_json


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steam-id')
    parser.add_argument('--region')
    parser.add_argument('--login-name', help='Steam account login name, not the display nickname')
    args = parser.parse_args()
    if os.getuid() != 988 or not sys.stdin.isatty():
        parser.error('run as hermes in your own interactive terminal')
    args.steam_id = args.steam_id or input('Expected SteamID64 (17 digits): ').strip()
    args.region = args.region or input('Actual Steam store country (CN/TW/US etc.): ').strip().upper()
    if not re.fullmatch(r'7656119[0-9]{10}', args.steam_id) or not re.fullmatch(r'[A-Z]{2}', args.region):
        parser.error('exact SteamID64 and real store country code required')
    if args.login_name and not re.fullmatch(r'[A-Za-z0-9_]{1,64}', args.login_name):
        parser.error('invalid Steam login name')
    os.umask(0o077)
    lock = (ROOT / 'private/qr-login.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError('another_steam_login_is_running') from None
    connection_path = ROOT / 'private/connection.json'
    if connection_path.stat().st_mode & 0o077 or connection_path.stat().st_uid != os.getuid():
        parser.error('IPC credential file must be owner-only')
    cfg = json.loads(connection_path.read_text())
    if cfg['ipc_url'] != 'http://127.0.0.1:1242' or cfg['bot'] != 'Main':
        parser.error('unexpected IPC endpoint or bot')
    settings_path = ROOT / 'private/steam.json'
    expected = {**cfg, 'steam_id': args.steam_id, 'region': args.region}
    if settings_path.exists():
        existing = json.loads(settings_path.read_text())
        if any(existing.get(k) != expected[k] for k in ('steam_id', 'region', 'bot', 'ipc_url')):
            raise RuntimeError('existing_adapter_identity_differs_review_required')
    opener = build_opener(ProxyHandler({}), NoRedirect())
    prefix = '/Api/Bot/' + cfg['bot']

    def request(route, payload=None, post=False):
        data = json.dumps(payload).encode() if payload is not None else None
        req = Request(cfg['ipc_url'] + route, data=data, method='POST' if post else 'GET',
                      headers={'Authentication': cfg['ipc_password'], 'Content-Type': 'application/json'})
        try:
            with opener.open(req, timeout=20) as response:
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
        if not isinstance(value, dict) or set(value) != {cfg['bot']}:
            raise RuntimeError('unexpected_bot_response')
        return value[cfg['bot']]

    def provide(kind, value):
        request(prefix + '/Input', {'Type': kind, 'Value': value}, post=True)

    login_name = None
    cleanup_needed = [False]

    def stop_incomplete_login():
        if cleanup_needed[0]:
            try:
                if bot().get('KeepRunning'):
                    request(prefix + '/Stop', post=True)
            except Exception:
                pass

    atexit.register(stop_incomplete_login)
    global_config = request('/Api/ASF').get('GlobalConfig', {})
    if global_config.get('Headless') is not True or global_config.get('Debug') is not False:
        raise RuntimeError('unsafe_logging_configuration')
    current = bot()
    if current.get('BotConfig', {}).get('EnableFreePackages') is not False:
        raise RuntimeError('background_free_packages_must_be_disabled')
    if not current.get('IsConnectedAndLoggedOn'):
        if current.get('KeepRunning'):
            request(prefix + '/Stop', post=True)
        print('Authorize NAS login for SteamID ' + args.steam_id + ', store country ' + args.region + '.')
        login_name = args.login_name or getpass.getpass('Steam login name (hidden): ')
        password = getpass.getpass('Steam password (hidden; memory only): ')
        if not login_name or not password:
            raise RuntimeError('empty_login_input')
        provide(1, login_name)
        provide(2, password)
        del password
        cleanup_needed[0] = True
        request(prefix + '/Start', post=True)
        provided = set()
        until = time.monotonic() + 240
        print('Waiting for Steam; approve the device in your Steam mobile app if prompted.')
        while time.monotonic() < until:
            current = bot()
            if current.get('IsConnectedAndLoggedOn'):
                break
            kind = current.get('RequiredInput', 0)
            if kind in (3, 4, 5, 7) and kind not in provided:
                provided.add(kind)
                if kind == 7:
                    input('Approve this login in Steam mobile, then press Enter: ')
                    code = 'Y'
                else:
                    label = {3: 'Steam Guard email code', 4: 'Family PIN', 5: 'Steam Guard mobile code'}[kind]
                    code = getpass.getpass(label + ' (hidden; memory only): ')
                provide(kind, code)
                del code
                if not current.get('KeepRunning'):
                    request(prefix + '/Start', post=True)
            elif kind in (1, 2) and not current.get('KeepRunning'):
                raise RuntimeError('login_rejected_or_more_input_required')
            elif kind in provided and not current.get('KeepRunning'):
                raise RuntimeError('guard_not_accepted_no_automatic_retry')
            elif not current.get('KeepRunning'):
                raise RuntimeError('steam_login_stopped_no_automatic_retry')
            time.sleep(2)
        else:
            if bot().get('KeepRunning'):
                request(prefix + '/Stop', post=True)
            raise RuntimeError('login_deadline_exceeded')
    if str(current.get('s_SteamID', current.get('SteamID'))) != args.steam_id:
        request(prefix + '/Stop', post=True)
        raise RuntimeError('steam_account_mismatch_bot_stopped')
    # ASF requires the login name alongside its refresh token after restart.
    # Only the account name is stored; password/code IPC inputs stay transient.
    bot_path = ROOT / 'config/Main.json'
    bot_cfg = json.loads(bot_path.read_text())
    if any(bot_cfg.get(k) for k in ('SteamPassword', 'SteamParentalCode')):
        raise RuntimeError('unexpected_saved_secret_review_required')
    login_name = login_name or bot_cfg.get('SteamLogin') or getpass.getpass('Steam login name for restart reconnect (hidden): ')
    if not login_name:
        raise RuntimeError('empty_login_name')
    bot_cfg.update(Enabled=True, EnableFreePackages=False, FarmingPreferences=1,
                   RemoteCommunication=0, OnlineStatus=0, SteamLogin=login_name)
    private_json(bot_path, bot_cfg)
    settings = {**cfg, 'steam_id': args.steam_id, 'region': args.region,
                'discovery': {'change_number': 0, 'max_packages': 30}}
    if not settings_path.exists():
        private_json(settings_path, settings)
    cleanup_needed[0] = False
    print('Steam identity verified; private adapter config saved. Read-only acceptance can begin.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, KeyError, OSError) as error:
        # Never render an HTTP response, arbitrary exception or sensitive value.
        reason = str(error) if isinstance(error, RuntimeError) else 'local_configuration_error'
        print('Login stopped: ' + reason, file=sys.stderr)
        raise SystemExit(1)
