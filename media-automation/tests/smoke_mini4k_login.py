"""Focused offline smoke: NAS login, cross-process lock, auth reason and MCP default."""
import asyncio
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from mcp import Client

from media_capabilities.acquisition import mini4k_login
from media_capabilities.acquisition.models import AcquisitionRequest, ResourceCandidate
from media_capabilities.acquisition.moviepilot_host import Mini4KAdapter
from media_capabilities.acquisition.public_index import (
    DownloadLink, IndexFailure, IndexStatus, LinuxBrowserTransport, Mini4KIndexer, ResolvedCandidate,
)
from media_download_mcp.server import create_server


class Page:
    def __init__(self):
        self.calls = []
        self.waiting_for_navigation = False

    def locator(self, selector):
        class Element:
            def count(self): return 1
            def fill(element, value): self.calls.append((selector, 'fill', value))
            def click(element):
                assert self.waiting_for_navigation, 'subscribe to the form navigation before clicking'
                self.calls.append((selector, 'click'))
        return Element()

    @contextmanager
    def expect_navigation(self, **kwargs):
        assert kwargs == {'wait_until': 'domcontentloaded', 'timeout': 30000}
        self.calls.append(('navigation', 'begin'))
        self.waiting_for_navigation = True
        try:
            yield
        finally:
            self.waiting_for_navigation = False
            self.calls.append(('navigation', 'committed'))


class Browser:
    def __init__(self, html):
        self.page, self.html, self.closed, self.visits = Page(), html, False, []

    @contextmanager
    def open_context(self):
        try:
            yield SimpleNamespace(pages=[self.page])
        finally:
            self.closed = True

    def navigate(self, context, page, url, **kwargs):
        self.visits.append((url, kwargs))
        return self.html


def form_smoke():
    browser = Browser('<a href="/download/test.torrent">下载种子</a>')
    result = ResolvedCandidate(IndexStatus.OK, mini4k_login.DEFAULT_CANDIDATE,
        (DownloadLink('magnet', info_hash='a' * 40),))
    def verified(indexer, candidate):
        assert browser.closed, 'check saved session only after releasing the browser'
        return result
    with patch.object(mini4k_login, 'verify_resource', verified):
        assert mini4k_login.login(browser, 'smoke-user', 'smoke-password') == result
    assert browser.page.calls[:5] == [('#edit-name', 'fill', 'smoke-user'),
        ('#edit-pass', 'fill', 'smoke-password'), ('navigation', 'begin'),
        ('#user-login-form input[type="submit"]', 'click'), ('navigation', 'committed')]
    assert browser.visits[0] == (mini4k_login.LOGIN_URL, {'allow_login': True})
    blocked = Browser('<a href="/user/login">下载需登录</a>')
    try:
        mini4k_login.login(blocked, 'smoke-user', 'smoke-password')
        raise AssertionError('cookie presence cannot prove download permission')
    except IndexFailure as exc:
        assert exc.status == IndexStatus.AUTH_REQUIRED and blocked.closed
    share_only = SimpleNamespace(_candidate_target=lambda cid: ('https://mini4k.io/torrents/1', None),
        resolve=lambda cid: ResolvedCandidate(IndexStatus.OK, cid, (DownloadLink('115_share'),)))
    try:
        mini4k_login.verify_resource(share_only, 'candidate')
        raise AssertionError('a share is not proof of torrent access')
    except IndexFailure as exc:
        assert exc.status == IndexStatus.LINK_INVALID


def lock_smoke():
    with tempfile.TemporaryDirectory() as directory:
        browser = LinuxBrowserTransport(directory)
        code = """
import sys
from media_capabilities.acquisition.public_index import LinuxBrowserTransport, IndexFailure, IndexStatus
try:
    with LinuxBrowserTransport(sys.argv[1]).profile_lock(timeout=0):
        pass
except IndexFailure as exc:
    assert exc.status == IndexStatus.UNAVAILABLE and '使用中' in exc.reason
    raise SystemExit(7)
raise SystemExit(0)
"""
        with browser.profile_lock():
            held = subprocess.run([sys.executable, '-c', code, directory], capture_output=True)
            assert held.returncode == 7, held.stderr.decode()
        released = subprocess.run([sys.executable, '-c', code, directory], capture_output=True)
        assert released.returncode == 0, released.stderr.decode()
        assert (Path(directory) / '.mini4k-session.lock').stat().st_mode & 0o077 == 0


def auth_reason_smoke():
    class AuthBrowser:
        @contextmanager
        def open(self): yield self
        def goto(self, url): raise IndexFailure(IndexStatus.AUTH_REQUIRED)
    indexer = Mini4KIndexer(browser=AuthBrowser())
    result = indexer.resolve(mini4k_login.DEFAULT_CANDIDATE)
    assert result.status == IndexStatus.AUTH_REQUIRED and 'mini4k-login' in result.reason
    adapter = Mini4KAdapter(SimpleNamespace(p115_route_enabled=True), lambda: indexer, lambda: None)
    try:
        adapter.resolve(ResourceCandidate(mini4k_login.DEFAULT_CANDIDATE, 'mini4k', 'Movie'), None)
        raise AssertionError('authentication failure must reach the receipt warning')
    except ValueError as exc:
        assert 'AUTH_REQUIRED' in str(exc) and 'mini4k-login' in str(exc)


def secret_smoke():
    class TTY(io.StringIO):
        def isatty(self): return True
    out, err = io.StringIO(), TTY()
    with patch.object(sys, 'stdin', TTY()), redirect_stdout(out), redirect_stderr(err), \
         patch('builtins.input', return_value='smoke-user'), \
         patch.object(mini4k_login.getpass, 'getpass', return_value='never-log-this'), \
         patch.object(mini4k_login, 'login', side_effect=RuntimeError('never-log-this')):
        assert mini4k_login.main([]) == 1
    assert 'never-log-this' not in out.getvalue() + err.getvalue()


def login_stage_smoke():
    for exception, suffix in ((TimeoutError('never-log-this'), '超时'),
                              (RuntimeError('never-log-this'), '失败（RuntimeError）')):
        try:
            with mini4k_login.login_step('提交登录表单并等待导航'):
                raise exception
        except IndexFailure as exc:
            assert exc.status == IndexStatus.UNAVAILABLE
            assert exc.reason == 'Mini4K 提交登录表单并等待导航' + suffix
            assert 'never-log-this' not in str(exc)


async def policy_smoke():
    payloads = []
    bridge = SimpleNamespace(download=lambda payload: payloads.append(payload) or {'status': 'smoke'})
    async with Client(create_server(bridge)) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        for name in ('search_resources', 'download_media', 'check_media'):
            policy = tools[name].input_schema['$defs']['AcquisitionRequest']['properties']['policy']
            assert policy['default'] == 'quality' and '用户明确' in policy['description']
        await client.call_tool('check_media', {'request': {'title': 'Movie'}})
        await client.call_tool('download_media', {'request': {'title': 'Movie', 'policy': 'balanced'}})
    assert [p['policy'] for p in payloads] == ['quality', 'balanced']
    assert AcquisitionRequest(title='Movie').policy == 'quality'


if __name__ == '__main__':
    form_smoke()
    lock_smoke()
    auth_reason_smoke()
    secret_smoke()
    login_stage_smoke()
    asyncio.run(policy_smoke())
    print('Mini4K NAS login smoke passed: form, lock, auth reason, secret handling and quality default')
