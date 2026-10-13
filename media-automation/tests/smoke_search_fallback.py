"""Focused offline smoke: missing metadata must not prevent resource search."""
import asyncio
from contextlib import contextmanager
import sys
import time
from types import ModuleType, SimpleNamespace

from mcp import Client

from media_capabilities.acquisition.models import AcquisitionRequest, MediaIdentity, SearchTarget
from media_capabilities.acquisition.moviepilot_host import MTeamAdapter, Mini4KAdapter
from media_capabilities.acquisition.public_index import Mini4KIndexer
from media_capabilities.acquisition.runtime import AcquisitionSettings
from media_capabilities.acquisition.service import AcquisitionService, SubmissionRegistry
from media_capabilities.store import MemoryTaskStore
from media_download_mcp.server import create_server


class Identities:
    def __init__(self, result=(), error=False):
        self.result, self.error = result, error

    def identify(self, request):
        if self.error:
            raise RuntimeError('upstream URL with protected credential')
        return list(self.result)


class Browser:
    downloads = 0

    @contextmanager
    def open(self):
        yield self

    def goto(self, url):
        return {
            'https://mini4k.io/search?text=Big%20Buck%20Bunny':
                '<a href="/movies/1">大雄兔 Big Buck Bunny</a><a href="/movies/2">另一版本</a>',
            'https://mini4k.io/movies/1': '<h1>大雄兔 Big Buck Bunny (2008)</h1>'
                '<table><tr><td><a href="/torrents/1">Big.Buck.Bunny.2008.1080p.mp4</a></td></tr></table>',
            'https://mini4k.io/movies/2': '<h1>Big Buck Bunny (2009)</h1>'
                '<table><tr><td><a href="/torrents/2">Big.Buck.Bunny.2009.1080p.mp4</a></td></tr></table>',
        }[url]


class Downloader:
    calls = 0

    def submit(self, *args):
        self.calls += 1
        raise AssertionError('unverified search reached downloader')


queries = []


def context(title, tmdb_id=1):
    return SimpleNamespace(torrent_info=SimpleNamespace(site=1, category='movie', title=title,
        page_url='https://mteam.invalid/' + title, size=100, seeders=2, description=''),
        media_info=SimpleNamespace(tmdb_id=tmdb_id, type='movie'), meta_info=None)


class SearchChain:
    def search_by_title(self, query, **kwargs):
        queries.append(query)
        return [context('Big.Buck.Bunny.2008.1080p.WEB-DL'),
                context('Big.Buck.Bunny.2009.1080p.WEB-DL'),
                context('Other.Movie.2008.1080p.WEB-DL')]


def wait_search(engine, payload):
    result = engine.start_search(payload)
    deadline = time.monotonic() + 2
    while result['status'] == 'pending' and time.monotonic() < deadline:
        time.sleep(.01)
        result = engine.search_status(result['session_id'])
    return result


def main():
    old = sys.modules.get('app.chain.search')
    module = ModuleType('app.chain.search')
    module.SearchChain = SearchChain
    sys.modules['app.chain.search'] = module
    try:
        for error in (False, True):
            identity, browser, downloader = Identities(error=error), Browser(), Downloader()
            settings = AcquisitionSettings(enabled=True)
            index = Mini4KIndexer(browser, base_url='https://mini4k.io')
            engine = AcquisitionService(identity, [MTeamAdapter(settings, identity),
                Mini4KAdapter(settings, lambda: index, lambda: None)], downloader,
                SubmissionRegistry(MemoryTaskStore()))
            try:
                result = wait_search(engine, {'title': 'Big Buck Bunny', 'year': 2008})
                assert result['status'] == 'complete' and result['identity_status'] == 'unverified', result
                assert result['media']['media_type'] is None and result['media']['year'] == 2008
                assert result['warnings'] and 'protected' not in str(result)
                assert len(result['candidates']) == 2 and all(s['status'] == 'OK' for s in result['sources'].values()), result
                assert queries[-1] == 'Big Buck Bunny 2008' and browser.downloads == 0
                assert all('2008' in c['title'] for c in result['candidates'])
                page = engine.more(result['session_id'], 'mteam')
                deadline = time.monotonic() + 2
                while page['status'] == 'pending' and time.monotonic() < deadline:
                    time.sleep(.01)
                    page = engine.search_status(result['session_id'])
                assert page['status'] == 'complete' and page['identity_status'] == 'unverified'
                receipt = engine.download({'candidate_id': result['candidates'][0]['candidate_id']})
                assert receipt['status'] == 'failed' and '身份尚未核实' in receipt['reason'], receipt
                before = len(queries)
                receipt = engine.download({'title': 'Big Buck Bunny', 'year': 2008})
                assert receipt['status'] == ('failed' if error else 'no_match'), receipt
                assert len(queries) == before and downloader.calls == 0

                class Bridge:
                    def search(self, payload): return wait_search(engine, payload)

                async def check_mcp():
                    async with Client(create_server(Bridge())) as client:
                        tools = await client.list_tools()
                        assert len(tools.tools) == 3
                        reply = await client.call_tool('search_resources',
                            {'request': {'title': 'Big Buck Bunny', 'year': 2008}})
                        assert reply.structured_content['identity_status'] == 'unverified'
                        assert len(reply.structured_content['candidates']) == 2
                asyncio.run(check_mcp())
            finally:
                engine.close()

        ambiguous = AcquisitionService(Identities([MediaIdentity('A', 'movie', 1),
            MediaIdentity('B', 'movie', 2)]), [], Downloader(), SubmissionRegistry(MemoryTaskStore()))
        try:
            assert wait_search(ambiguous, {'title': 'Bunny'})['status'] == 'needs_selection'
        finally:
            ambiguous.close()
        unknown = AcquisitionService(Identities(), [], Downloader(), SubmissionRegistry(MemoryTaskStore()))
        try:
            assert wait_search(unknown, {'tmdb_id': 1, 'media_type': 'movie'})['status'] == 'no_match'
            tv = unknown._target(AcquisitionRequest(title='Series', media_type='tv', season=2), search_only=True)[0]
            assert isinstance(tv, SearchTarget) and tv.season == 2 and not tv.expected
        finally:
            unknown.close()
    finally:
        if old is None:
            sys.modules.pop('app.chain.search', None)
        else:
            sys.modules['app.chain.search'] = old
    print('search fallback smoke: both sources, bilingual title/year, metadata outage, pagination, MCP and download guard OK')


if __name__ == '__main__':
    main()
