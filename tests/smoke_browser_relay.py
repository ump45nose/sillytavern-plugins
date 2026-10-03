"""One smoke for CF checkbox renewal and anonymous/authenticated origin routing."""
import base64
import sys
import tempfile
import types
from pathlib import Path

import bencode

root = Path(__file__).resolve().parents[1] / 'plugins.v2' / 'filmwatchlist'
package = types.ModuleType('filmwatchlist')
package.__path__ = [str(root)]
sys.modules['filmwatchlist'] = package

from filmwatchlist.access import page_access_status
from filmwatchlist.browser_relay import BrowserRelayTransport
from filmwatchlist.public_index import IndexStatus, Mini4KIndexer

assert page_access_status('<title>Film</title><script src="https://challenges.cloudflare.com/widget"></script>') is None
assert page_access_status('<title>登录</title><input type="password">') == 'AUTH_REQUIRED'
assert page_access_status('<title>Just a moment...</title>') == 'CF_CHALLENGE'

content = bencode.bencode({b'info': {b'name': b'film.mkv', b'length': 1234}})


class Relay(BrowserRelayTransport):
    def __init__(self, directory):
        super().__init__(tab_id_path=str(directory / 'tab'), origin_path=str(directory / 'origin'))
        self.tab_id_path.write_text('t_test123456')
        self.tab_id_path.chmod(0o600)
        self.url = ''
        self.passed = False
        self.clicks = 0
        self.download_failure = False
        self.background = False

    def _rpc(self, method, path, body=None):
        if path == '/api/tabs':
            return {'tabs': [{'id': 't_test123456'}]}
        if path == '/api/navigate':
            self.url = body['url'].replace('https://mini4k.com/', 'https://www.mini4k.com/')
            return {'url': self.url}
        if path.startswith('/api/snapshot'):
            if 'mini4k.io' in self.url:
                html = '<a href="/user/login">点击下载种子文件</a>'
            elif not self.passed:
                html = '<title>请稍候…</title>'
            else:
                html = '<title>Film</title><a href="/download/film.torrent">下载</a>'
            return {'html': html + ' ' * 600, 'url': self.url}
        if path == '/api/observe':
            return {'background': self.background,
                    'frames': [{'id': 'cf', 'url': 'https://challenges.cloudflare.com/widget'}],
                    'nodes': [{'ref': 'e1_1', 'role': 'checkbox', 'name': '请验证您是真人',
                               'frameId': 'cf', 'checked': 'false'}]}
        if path == '/api/actions':
            if body['actions'] == [{'type': 'focus'}]:
                return {'task': {'status': 'completed'}}
            assert body['actions'] == [{'type': 'click', 'target': {'ref': 'e1_1'}}]
            self.passed = True
            self.clicks += 1
            return {'task': {'status': 'completed'}}
        if path == '/api/eval':
            assert 'https://www.mini4k.com/download/film.torrent' in body['expression']
            if self.download_failure:
                return {'result': {'value': {'http_status': 403,
                                             'access_html': '<title>Just a moment...</title>'}}}
            return {'result': {'value': base64.b64encode(content).decode()}}
        raise AssertionError(path)


with tempfile.TemporaryDirectory() as directory:
    transport = Relay(Path(directory))
    indexer = Mini4KIndexer(browser=transport)
    candidate = indexer._candidate_id('https://mini4k.io/torrents/123')
    resolved = indexer.resolve(candidate)
    assert resolved.status == IndexStatus.OK, resolved
    assert resolved.links[0].torrent_bytes == content
    assert transport.clicks == 1
    assert transport.origin_path.read_text() == 'https://www.mini4k.com'
    assert transport.origin_path.stat().st_mode & 0o077 == 0
    assert indexer.resolve(candidate).status == IndexStatus.OK
    assert transport.clicks == 1, 'reuse working origin without repeating challenge'
    transport.download_failure = True
    assert indexer.resolve(candidate).status == IndexStatus.CF_CHALLENGE
    transport.background = True
    transport.passed = False
    assert transport._complete_challenge('t_test123456') is False
    assert transport.clicks == 1, 'background focus success must not imply CF passed'

print('Relay smoke passed: CF semantic action, origin isolation, torrent and session reuse')
