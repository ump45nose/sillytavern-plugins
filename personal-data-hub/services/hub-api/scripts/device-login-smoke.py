#!/usr/bin/env python3
"""Interactive desktop acceptance: browser/loopback, real device, API reads, revocation.

Uses Python's standard library. Keeps all credentials in memory and reports only
HTTP status, module status and row counts. Does not modify source business records.
"""
import argparse
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer


def report(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='https://hub-home.172906573.xyz:28443')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    target = urllib.parse.urlsplit(base)
    if target.scheme != 'https' or not target.hostname or target.username or target.password or target.query or target.fragment:
        raise ValueError('HTTPS base URL required')
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    state = secrets.token_urlsafe(32)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs contain one-time credentials.

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(parsed.query)
            received_state = query.get('state', [''])[0]
            code = query.get('code', [''])[0]
            valid = (parsed.path == '/callback' and hmac.compare_digest(received_state.encode(), state.encode())
                     and 1 <= len(code) <= 128)
            if valid:
                result['code'] = code
            body = ('登录回调已接收，可以关闭此页。' if valid else '回调无效，请返回登录窗口重试。').encode()
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        server.timeout = 1
        url = base + '/auth/start?' + urllib.parse.urlencode({
            'device_name': 'Desktop browser acceptance (temporary)',
            'redirect_uri': f'http://127.0.0.1:{server.server_port}/callback',
            'code_challenge': challenge, 'state': state,
        })
        if not webbrowser.open(url):
            raise RuntimeError('desktop browser unavailable')
        report(step='browser', action='请在已打开的浏览器完成 Authelia 登录和授权')
        deadline = time.monotonic() + 600
        while 'code' not in result and time.monotonic() < deadline:
            server.handle_request()
        if 'code' not in result:
            raise TimeoutError('browser login timed out')

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(path, method='GET', body=None, token=None):
        headers = {'Accept': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(base + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        with opener.open(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None

    _, pair = api('/auth/token', 'POST', {'code': result.pop('code'), 'code_verifier': verifier})
    revoked = False
    try:
        token = pair['token']
        status, data = api('/api/v1/modules', token=token)
        report(step='modules', http=status, modules={
            key: {'status': value['status'], 'counts': {
                field: len(rows) for field, rows in (value.get('data') or {}).items() if isinstance(rows, list)
            }} for key, value in data['modules'].items()
        })
        status, data = api('/api/v1/status', token=token)
        report(step='status', http=status, sources=len(data['sources']))
        status, _ = api('/api/v1/devices/' + pair['device_id'], 'DELETE', token=token)
        if status != 204:
            raise RuntimeError('device revocation failed')
        revoked = True
        try:
            api('/api/v1/status', token=token)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
        else:
            raise RuntimeError('revoked device was accepted')
        report(success=True, browser_loopback=True, token_exchange=True, revocation_http=401)
    finally:
        if not revoked:
            try:
                api('/api/v1/devices/' + pair['device_id'], 'DELETE', token=pair['token'])
                report(cleanup_revoked=True)
            except Exception:
                report(cleanup_revoked=False, device_id=pair['device_id'])


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        report(success=False, error=type(error).__name__, http=getattr(error, 'code', None))
        raise SystemExit(1)
