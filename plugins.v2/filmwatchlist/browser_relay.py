"""Optional Mini4K browser session fallback via Browser Relay Remote Relay.

The Device ID is read from a protected file at call time. It is never returned
to the indexer, API responses or plugin records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests

from .access import download_requires_login, has_download_link, page_access_status


class RelayUnavailable(Exception):
    pass


class BrowserRelayTransport:
    """Reuse a dedicated tab and learn the origin with working download access."""

    origins = ('https://mini4k.com', 'https://www.mini4k.com', 'https://mini4k.io')

    def __init__(self, device_id_path: str = "/config/filmwatchlist-browser-relay.device-id",
                 relay_host: str = "https://relay.linso.ai",
                 tab_id_path: str = "/config/filmwatchlist-browser-relay.tab-id",
                 origin_path: str = "/config/filmwatchlist-browser-relay.download-origin"):
        self.device_id_path = Path(device_id_path)
        self.tab_id_path = Path(tab_id_path)
        self.origin_path = Path(origin_path)
        self.relay_host = relay_host.rstrip("/")
        self._lock = Lock()

    def _read_origin(self) -> str | None:
        if not self.origin_path.is_file():
            return None
        if self.origin_path.stat().st_mode & 0o077:
            raise RelayUnavailable('Relay 会话域名文件权限不安全')
        value = self.origin_path.read_text().strip()
        return value if value in self.origins else None

    def _save_origin(self, value: str):
        if value not in self.origins:
            raise RelayUnavailable('Relay 会话域名无效')
        fd = os.open(self.origin_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(value)
        self.origin_path.chmod(0o600)

    def _complete_challenge(self, tab_id: str) -> bool:
        """Use a verified Cloudflare frame's checkbox, never screenshot coordinates."""
        self._rpc('POST', '/api/actions', {
            'tabId': tab_id, 'actions': [{'type': 'focus'}],
            'observe': 'none', 'timeoutMs': 15000,
        })
        time.sleep(0.6)
        observed = self._rpc('POST', '/api/observe', {
            'tabId': tab_id, 'mode': 'snapshot', 'includeNodes': True, 'maxLength': 20000,
        })
        # Relay can report focus/click as completed while Chrome is minimized.
        # A synthetic background click does not prove Cloudflare verification.
        if observed.get('background') is not False:
            return False
        frames = {f.get('id') for f in observed.get('frames') or []
                  if urlparse(f.get('url', '')).hostname == 'challenges.cloudflare.com'}
        controls = [node for node in observed.get('nodes') or []
                    if node.get('frameId') in frames and node.get('role') == 'checkbox'
                    and str(node.get('checked')).lower() != 'true'
                    and any(marker in (node.get('name') or '').casefold()
                            for marker in ('真人', 'human', 'verify'))]
        if len(controls) != 1 or not controls[0].get('ref'):
            return False
        result = self._rpc('POST', '/api/actions', {
            'tabId': tab_id,
            'actions': [{'type': 'click', 'target': {'ref': controls[0]['ref']}}],
            'observe': 'none', 'timeoutMs': 15000,
        })
        if (result.get('task') or {}).get('status') != 'completed':
            return False
        for _ in range(4):
            time.sleep(1)
            result = self._rpc('GET', '/api/snapshot?tabId=' + quote(tab_id)
                               + '&format=html&maxLength=1000000')
            html = result.get('html')
            if isinstance(html, str) and len(html) >= 500 \
                    and page_access_status(html) != 'CF_CHALLENGE':
                return True
        return False

    def _identity(self) -> tuple[str, str]:
        path = self.device_id_path
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise RelayUnavailable("Relay 凭据文件权限不安全")
        device_id = path.read_text().strip()
        match = re.fullmatch(r"br-([A-Za-z0-9_-]{16,})", device_id)
        if not match:
            raise RelayUnavailable("Relay Device ID 格式无效")
        secret = match.group(1)
        route_id = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode().rstrip("=")[:16]
        return secret, route_id

    def _rpc(self, method: str, path: str, body: dict | None = None) -> dict:
        secret, route_id = self._identity()
        request = {"routeId": route_id, "id": str(uuid.uuid4()), "method": method,
                   "path": path, "body": body, "headers": {}}
        try:
            response = requests.post(
                self.relay_host + "/v1/rpc", json=request,
                headers={"Authorization": "Bearer " + secret}, timeout=35,
            )
            data = response.json()
            if response.status_code >= 400 or data.get("ok") is False:
                raise RelayUnavailable("Relay 浏览器请求失败")
            return data
        except (requests.RequestException, ValueError) as exc:
            raise RelayUnavailable("Relay 服务不可用") from exc

    @staticmethod
    def _main_site_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ("mini4k.io", "mini4k.com", "www.mini4k.com") \
                or parsed.username or parsed.password or parsed.port:
            raise RelayUnavailable("拒绝访问非 Mini4K 地址")
        return urlunparse(parsed)

    @contextmanager
    def open(self):
        with self._lock:
            tab_id = None
            if self.tab_id_path.is_file():
                mode = self.tab_id_path.stat().st_mode
                if mode & 0o077:
                    raise RelayUnavailable("Relay 标签文件权限不安全")
                saved = self.tab_id_path.read_text().strip()
                if saved:
                    tabs = self._rpc("GET", "/api/tabs").get("tabs") or []
                    if any(tab.get("id") == saved for tab in tabs):
                        tab_id = saved
            if not tab_id:
                created = self._rpc("POST", "/api/tabs/create",
                                    {"url": "https://www.mini4k.com"})
                tab_id = created.get("tabId")
                if isinstance(tab_id, str):
                    fd = os.open(self.tab_id_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                    with os.fdopen(fd, "w") as handle:
                        handle.write(tab_id)
                    self.tab_id_path.chmod(0o600)
            if not isinstance(tab_id, str):
                raise RelayUnavailable("Relay 未创建浏览器标签")
            transport = self

            class Session:
                def __init__(self):
                    self.origin = transport._read_origin()
                    self.last_url = None
                    self.last_html = None

                def _read(self, target: str) -> str:
                    transport._rpc('POST', '/api/navigate', {'tabId': tab_id, 'url': target})
                    clicks = 0
                    deadline = time.monotonic() + 45
                    html = ''
                    while time.monotonic() < deadline:
                        result = transport._rpc(
                            'GET', '/api/snapshot?tabId=' + quote(tab_id)
                            + '&format=html&maxLength=1000000',
                        )
                        if result.get('truncated') or not isinstance(result.get('html'), str):
                            raise RelayUnavailable('Relay 页面内容不完整')
                        final = urlparse(result.get('url') or target)
                        if final.hostname not in ('mini4k.io', 'www.mini4k.com', 'mini4k.com'):
                            raise RelayUnavailable('Relay 页面跳转到非 Mini4K 地址')
                        html = result['html']
                        wanted = urlparse(target)
                        same_site = final.hostname == wanted.hostname or {
                            final.hostname, wanted.hostname} == {'www.mini4k.com', 'mini4k.com'}
                        if not same_site or (final.path != wanted.path and final.path != '/user/login'):
                            time.sleep(1)
                            continue
                        if len(html) < 500:
                            time.sleep(1)
                            continue
                        status = page_access_status(html)
                        if status == 'CF_CHALLENGE':
                            if clicks < 2:
                                clicks += 1
                                if transport._complete_challenge(tab_id):
                                    time.sleep(2)
                                    continue
                            time.sleep(1.5)
                            continue
                        if final.path == urlparse(target).path or final.path == '/user/login':
                            self.last_url = urlunparse(final)
                            self.last_html = html
                            return html
                        time.sleep(1)
                    return html

                def goto(self, url: str) -> str:
                    target = transport._main_site_url(url)
                    parsed = urlparse(target)
                    requested_origin = f'{parsed.scheme}://{parsed.netloc}'
                    gated = parsed.path.startswith('/torrents/')
                    origins = list(dict.fromkeys(x for x in
                                   (self.origin, requested_origin, *transport.origins) if x))
                    failures = []
                    for origin in origins:
                        mapped = urlunparse(parsed._replace(netloc=urlparse(origin).netloc))
                        html = self.last_html if self.last_url == mapped else self._read(mapped)
                        status = page_access_status(html)
                        if status == 'CF_CHALLENGE' or (gated and
                                (status == 'AUTH_REQUIRED' or download_requires_login(html))
                                and not has_download_link(html)):
                            failures.append((status or 'AUTH_REQUIRED', html))
                            continue
                        final = urlparse(self.last_url or mapped)
                        self.origin = f'{final.scheme}://{final.netloc}'
                        if gated and has_download_link(html):
                            transport._save_origin(self.origin)
                        return html
                    # An anonymous mirror must not hide a challenged authenticated origin.
                    html = next((h for status, h in failures if status == 'CF_CHALLENGE'),
                                failures[0][1] if failures else '')
                    return html

                def download(self, page_url: str, href: str) -> bytes:
                    html = self.goto(page_url)
                    if page_access_status(html):
                        from .public_index import IndexFailure, IndexStatus
                        raise IndexFailure(IndexStatus(page_access_status(html)))
                    target = transport._main_site_url(urljoin(
                        transport._main_site_url(page_url), href))
                    if self.origin:
                        target = urlunparse(urlparse(target)._replace(netloc=urlparse(self.origin).netloc))
                    expression = """(async () => {
                      const url = new URL(%s, location.href);
                      if (url.origin !== location.origin) throw new Error('cross-origin torrent');
                      const response = await fetch(url, {credentials: 'include'});
                      if (!response.ok) return {
                        http_status: response.status,
                        access_html: (await response.text()).slice(0, 100000)
                      };
                      const bytes = new Uint8Array(await response.arrayBuffer());
                      if (bytes.length > 10485760) throw new Error('torrent too large');
                      let binary = '';
                      for (let i = 0; i < bytes.length; i += 32768)
                        binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
                      return btoa(binary);
                    })()""" % json.dumps(target)
                    result = transport._rpc("POST", "/api/eval", {"tabId": tab_id,
                                                                 "expression": expression})
                    if result.get("exceptionDetails"):
                        raise RelayUnavailable("Relay 种子文件下载失败")
                    encoded = (result.get("result") or {}).get("value")
                    if isinstance(encoded, dict) and encoded.get('http_status'):
                        from .public_index import IndexFailure, IndexStatus
                        status = page_access_status(encoded.get('access_html') or '')
                        if not status and encoded['http_status'] in (401, 403):
                            status = 'AUTH_REQUIRED' if encoded['http_status'] == 401 else 'UNAVAILABLE'
                        raise IndexFailure(IndexStatus(status or 'LINK_INVALID'))
                    if not isinstance(encoded, str):
                        raise RelayUnavailable("Relay 未返回种子文件")
                    return base64.b64decode(encoded, validate=True)

            yield Session()
