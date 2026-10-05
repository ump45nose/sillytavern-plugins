"""Small offline smoke for the Mini4K index contract; no live download task."""

import sys
import types
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, parse_qs, urlparse

import bencode

root = Path(__file__).resolve().parents[1] / "plugins.v2" / "filmwatchlist"
package = types.ModuleType("filmwatchlist")
package.__path__ = [str(root)]
sys.modules["filmwatchlist"] = package

from filmwatchlist.public_index import IndexFailure, IndexStatus, MediaQuery, Mini4KIndexer


class FakeBrowser:
    def __init__(self, pages, torrent=None):
        self.pages = pages
        self.torrent = torrent
        self.downloads = 0

    @contextmanager
    def open(self):
        yield self

    def goto(self, url):
        result = self.pages[url]
        if isinstance(result, Exception):
            raise result
        return result

    def download(self, page_url, href):
        assert href == "/download/123.torrent"
        self.downloads += 1
        return self.torrent


base = "https://www.mini4k.com"
search = base + "/search?text=" + quote("基督山伯爵")
pages = {
    search: '<form></form><a href="/movies/1">法国版</a><a href="/movies/2">美国版</a>',
    base + "/movies/1": '''<h1>基督山伯爵 (2024)</h1><div>国家 法国</div>
      <table><tr><td><a href="/torrents/123">The.Count.of.Monte.Cristo.2024.2160p.Remux</a></td>
      <td>50 GB</td></tr><tr><td><a href="https://115.com/s/abc">115 分享</a></td></tr>
      <tr><td><a href="https://pan.quark.cn/s/def">夸克分享</a></td></tr></table>''',
    base + "/movies/2": '<h1>基督山伯爵 (2024)</h1><div>国家 美国</div>',
    base + "/torrents/123": '''<a href="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&amp;amp;tr=https%3A%2F%2Ftracker.example%2Fannounce">磁力</a>
      <a href="/download/123.torrent">下载种子</a>''',
}
torrent = bencode.bencode({b"info": {b"name": b"film.mkv", b"length": 1234}})
browser = FakeBrowser(pages, torrent)
indexer = Mini4KIndexer(browser, base_url=base)
query = MediaQuery("基督山伯爵", year=2024, country="法国", media_type="movie")
result = indexer.search(query)
assert result.status == IndexStatus.OK and len(result.candidates) == 3, result
assert all("/movies/1" in item.media_page_url for item in result.candidates)
assert browser.downloads == 0, "search must not resolve torrent files"

torrent_candidate = next(item for item in result.candidates if "/torrents/" in item.resource_page_url)
resolved = Mini4KIndexer(browser, base_url=base).resolve(torrent_candidate.candidate_id)
assert resolved.status == IndexStatus.OK, resolved
assert {link.kind for link in resolved.links} == {"magnet", "torrent"}, resolved
assert parse_qs(urlparse(next(x.value for x in resolved.links if x.kind == 'magnet')).query)['tr'] == ['https://tracker.example/announce']
assert next(link for link in resolved.links if link.kind == "torrent").files == ("film.mkv",)
assert browser.downloads == 1

other_candidate = next(item for item in result.candidates if item.link_hint == "other_cloud_share")
other = indexer.resolve(other_candidate.candidate_id)
assert other.status == IndexStatus.OK and [link.kind for link in other.links] == ["other_cloud_share"]

resource_html = pages[base + "/torrents/123"]
pages[base + "/torrents/123"] = '<a href="/user/login">点击使用磁力下载</a>'
assert indexer.resolve(torrent_candidate.candidate_id).status == IndexStatus.AUTH_REQUIRED
pages[base] = '<title>Mini4K</title>'
health = indexer.health()
assert health.status == IndexStatus.AUTH_REQUIRED and health.page_status == IndexStatus.OK
assert health.resolve_status == IndexStatus.AUTH_REQUIRED
pages[base + '/torrents/123'] += '<a href="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567">磁力</a>'
assert indexer.resolve(torrent_candidate.candidate_id).status == IndexStatus.OK
pages[base + '/torrents/123'] = '<a href="/user/login">点击使用磁力下载</a>'
relay = FakeBrowser({base + "/torrents/123": resource_html}, torrent)
fallback = Mini4KIndexer(browser, base_url=base, fallback_browser=relay)
assert fallback.resolve(torrent_candidate.candidate_id).status == IndexStatus.OK

share_candidate = next(item for item in result.candidates if item.link_hint == "115_share")
share = Mini4KIndexer(browser, base_url=base).resolve(share_candidate.candidate_id)
assert share.status == IndexStatus.OK and [link.kind for link in share.links] == ["115_share"], share
assert browser.downloads == 1

pages[search] = IndexFailure(IndexStatus.CF_CHALLENGE)
assert indexer.search(query).status == IndexStatus.CF_CHALLENGE
pages[search] = '<form><input type="password"></form>请登录'
assert indexer.search(query).status == IndexStatus.AUTH_REQUIRED
pages[search] = '<form><input name="text"></form><p>没有搜索结果</p>'
assert indexer.search(query).status == IndexStatus.NO_RESULTS

# Live Mini4K returns this markup for an unmatched foreign-language alias.
alias_names = ('Movie', 'The Movie', 'Gaqceva shoushenkidan')
alias_pages = {base + '/search?text=' + quote(name):
               '<a href="/movies/3">Movie</a>' for name in alias_names[:2]}
alias_pages[base + '/movies/3'] = '<h1>Movie (2025)</h1><table><tr><td><a href="/torrents/4">Movie.2160p.BluRay</a></td></tr></table>'
alias_url = base + '/search?text=' + quote(alias_names[2])
alias_pages[alias_url] = '<div class="search-count-label">0 个结果</div><div class="chart-list search">无任何结果，请尝试其它关键词。</div>'
alias_browser = FakeBrowser(alias_pages)
aliases = Mini4KIndexer(alias_browser, base_url=base)
alias_query = MediaQuery(alias_names[0], aliases=alias_names[1:], year=2025, media_type='movie')
first = aliases.search(alias_query)
second = aliases.search(alias_query, first.next_cursor)
empty = aliases.search(alias_query, second.next_cursor)
assert first.status == second.status == IndexStatus.OK
assert empty.status == IndexStatus.NO_RESULTS and empty.next_cursor is None
assert alias_browser.downloads == 0
alias_pages[alias_url] = '<div class="search-count-label">0 个结果</div>'
assert aliases.search(alias_query, second.next_cursor).status == IndexStatus.NO_RESULTS
alias_pages[alias_url] = '<h1>Unknown search layout</h1>'
assert aliases.search(alias_query, second.next_cursor).status == IndexStatus.PARSE_CHANGED
alias_pages[base + '/search?text=Movie'] = '<div class="content"><span class="meta-item year">2024</span><a href="/movies/3">Movie</a></div>'
assert aliases.search(alias_query).status == IndexStatus.NO_RESULTS
print("Mini4K index smoke: identity, torrent, magnet, cloud shares, CF, auth and empty passed")
