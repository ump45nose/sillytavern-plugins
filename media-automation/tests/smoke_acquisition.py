"""Small offline smoke for scopes, profiles, receipts and both entrypoints.

Run once with packages and both application directories on PYTHONPATH.
No live sites, downloads, library writes or broad regression suite.
"""
import asyncio
from dataclasses import asdict
from pathlib import Path
import tempfile
import time

import bencode
import httpx
from fastapi.testclient import TestClient
from mcp import Client

from media_capabilities.acquisition.client import BridgeClient, ConnectionSettings
from media_capabilities.acquisition.evidence import torrent_evidence
from media_capabilities.acquisition.models import (
    AcquisitionRequest, DownloadTarget, MediaIdentity, ResourceCandidate, SourcePage,
)
from media_capabilities.acquisition.policies import inspect_target, select_candidates, subtitle_evidence
from media_capabilities.acquisition.quality_selection import MediaCandidate
from media_capabilities.acquisition.service import AcquisitionService, SubmissionRegistry
from media_capabilities.store import MemoryTaskStore
from media_search.app import create_app
from media_download_mcp.server import create_http_app, create_server

GIB = 1024 ** 3


def content(title, size):
    return bencode.bencode({b'info': {b'name': (title + '.mkv').encode(), b'length': size, b'private': 0}})


class Identity:
    def identify(self, request):
        return [MediaIdentity('Movie', 'movie', 123, year=2025)]


class Source:
    def __init__(self, source_id, titles, failure=False):
        self.source_id, self.titles, self.failure = source_id, titles, failure
        self.public_source = source_id == 'mini4k'
        self.searches = self.inspections = 0

    def search(self, target, cursor=None):
        self.searches += 1
        if self.failure:
            return SourcePage('CF_CHALLENGE')
        return SourcePage('OK', [ResourceCandidate(str(i), self.source_id, title, size,
            subtitles=subtitle_evidence(title), native=content(title, size))
            for i, (title, size) in enumerate(self.titles)])

    def resolve(self, candidate, target):
        self.inspections += 1
        evidence = torrent_evidence(candidate.native, candidate.title)
        inspect_target(candidate.title, evidence.files, target)
        return [MediaCandidate('pt' if self.source_id == 'mteam' else 'public_bt', candidate.title,
            evidence.video_bytes, evidence.total_bytes, candidate.candidate_id, info_hash=evidence.info_hash,
            files=evidence.files, evidence={'subtitles': asdict(candidate.subtitles)})]


class Downloader:
    def __init__(self, store, uncertain=False):
        self.store, self.uncertain, self.calls = store, uncertain, 0

    def submit(self, candidate, target):
        assert any(r.get('phase') == 'submitting' for r in self.store.read()['jobs'].values())
        self.calls += 1
        if self.uncertain:
            raise TimeoutError('signed URL and credential must never reach the receipt')
        return {'status': 'submitted', 'download_hash': candidate.info_hash}

    def status(self, record):
        return {}


def service(sources, uncertain=False, public_only=False):
    store = MemoryTaskStore()
    downloader = Downloader(store, uncertain)
    return AcquisitionService(Identity(), sources, downloader, SubmissionRegistry(store),
                              public_only=public_only), downloader


def wait_search(engine, payload):
    result = engine.start_search(payload)
    deadline = time.monotonic() + 2
    while result['status'] == 'pending' and time.monotonic() < deadline:
        time.sleep(.01)
        result = engine.search_status(result['session_id'])
    assert result['status'] == 'complete', result
    return result


def main():
    media = MediaIdentity('Series', 'tv', 7, episodes=((1, 1), (2, 1), (2, 2)), ended=True)
    full = DownloadTarget.build(media, AcquisitionRequest(title='Series', scope='series'))
    inspect_target('Series.COMPLETE', ['S01E01.mkv', 'S02E01-E02.mkv'], full)
    second = DownloadTarget.build(media, AcquisitionRequest(title='Series', season=2))
    inspect_target('Series.S02', ['S02E01.mkv', 'S02E02.mkv'], second)
    inspect_target('Series.S02', ['Series.S02E01.1080p.WEB-DL.mkv', 'Series.S02E02.2160p.mkv'], second)
    inspect_target('Series.S02', ['S02E01E02.1080p.mp4'], second)
    single = DownloadTarget.build(media, AcquisitionRequest(title='Series', scope='episode', season=2, episode=1))
    inspect_target('Series.S02E01', ['S02E01.mkv'], single)
    for target, files in ((full, ['S01E01.mkv']), (single, ['S02E01.mkv', 'S02E02.mkv']),
                         (second, ['S02E01E03.mkv'])):
        try:
            inspect_target('Series', files, target)
            raise AssertionError('incomplete/oversized target was accepted')
        except ValueError:
            pass
    try:
        DownloadTarget.build(MediaIdentity('Series', 'tv', 7, episodes=((1,1),)), AcquisitionRequest(title='Series', scope='series'))
        raise AssertionError('ongoing series was accepted')
    except ValueError:
        pass
    try:
        AcquisitionRequest(title='Series', scope='episode', episode=1)
        raise AssertionError('episode scope silently defaulted to first season')
    except ValueError:
        pass
    assert not subtitle_evidence('MULTI').chinese
    assert subtitle_evidence(files=['movie.zh-CN.srt']).kind == 'sidecar'

    pt = Source('mteam', [('Movie.2025.2160p.Remux', 50*GIB), ('Movie.2025.2160p.WEB-DL.CHS', 25*GIB)])
    public = Source('mini4k', [('Movie.2025.2160p.Remux', 46*GIB), ('Movie.2025.2160p.WEB-DL', 18*GIB)])
    engine, downloader = service([pt, public])
    search = wait_search(engine, {'title': 'Movie'})
    assert len(search['candidates']) == 4 and pt.inspections == public.inspections == 0
    wait_search(engine, {'title': 'Movie'})
    assert pt.searches == public.searches == 1, 'successful search cache not reused'
    receipt = engine.download({'title': 'Movie', 'request_id': 'quality'})
    assert receipt['status'] == 'submitted' and receipt['route'] == 'public_bt', receipt
    assert pt.inspections == public.inspections == 1, 'lower tiers eagerly inspected'
    engine.download({'title': 'Movie', 'request_id': 'quality'})
    duplicate = engine.download({'title': 'Movie', 'request_id': 'duplicate'})
    assert downloader.calls == 1 and duplicate['reused']
    assert engine.download({'title': 'Movie', 'request_id': 'duplicate'})['reused']
    balanced = engine.download({'title': 'Movie', 'policy': 'balanced', 'request_id': 'balanced'})
    assert balanced['resource']['video_bytes'] == 18*GIB, balanced
    subbed = engine.download({'title': 'Movie', 'policy': 'subtitle', 'request_id': 'subtitle'})
    assert subbed['resource']['subtitles']['chinese'], subbed
    target = DownloadTarget.build(Identity().identify(None)[0], AcquisitionRequest(title='Movie'))
    ranked, warnings = select_candidates([MediaCandidate('pt','Movie.2160p.WEB-DL',18*GIB,18*GIB,'x')], target, 'subtitle')
    assert ranked and warnings
    manual = engine.download({'candidate_id': search['candidates'][0]['candidate_id'],
        'policy': 'balanced', 'request_id': 'manual'})
    assert manual['policy'] == 'manual' and manual['resource']['video_bytes'] == 50*GIB
    engine.close()

    private = Source('mteam', [('Movie.2160p.Remux', 50*GIB)])
    public = Source('mini4k', [('Movie.1080p.BluRay', 10*GIB)])
    restricted, down = service([private, public], public_only=True)
    receipt = restricted.download({'title': 'Movie', 'request_id': 'public-only'})
    assert receipt['route'] == 'public_bt' and receipt['status'] == 'submitted'
    assert receipt['sources']['mteam']['status'] == 'SKIPPED' and not receipt['warnings']
    assert private.searches == private.inspections == 0
    # Search and explicit user choice remain available for PT.
    result = wait_search(restricted, {'title': 'Movie'})
    ref = next(c['candidate_id'] for c in result['candidates'] if c['source_id'] == 'mteam')
    manual = restricted.download({'candidate_id': ref, 'request_id': 'manual-pt'})
    assert manual['route'] == 'pt' and manual['policy'] == 'manual'
    restricted.close()
    no_public, down = service([Source('mteam', [('Movie.2160p.Remux', 10*GIB)]),
                              Source('mini4k', [], True)], public_only=True)
    assert no_public.download({'title':'Movie'})['status'] == 'unavailable' and down.calls == 0
    assert no_public.sources['mteam'].searches == 0
    no_public.close()

    tiers, down = service([Source('mteam', [('Movie.2160p.WEB-DL', 10*GIB),
        ('Movie.2160p.WEBRip', 9*GIB), ('Movie.1080p.BluRay', 12*GIB)])])
    assert '1080p.BluRay' in tiers.download({'title': 'Movie'})['resource']['title']
    tiers.close()

    partial, down = service([Source('mteam', [('Movie.2160p.Remux', 10*GIB)]), Source('mini4k', [], True)])
    result = partial.download({'title':'Movie'})
    assert result['status'] == 'submitted' and result['warnings'] and down.calls == 1
    partial.close()

    uncertain, down = service([Source('mteam', [('Movie.2160p.Remux', 10*GIB)])], True)
    receipt = uncertain.download({'title':'Movie', 'request_id':'uncertain'})
    assert receipt['status'] == 'pending' and 'signed URL' not in str(receipt)
    assert uncertain.download({'title':'Movie', 'request_id':'retry'})['status'] == 'pending'
    assert down.calls == 1
    uncertain.close()

    class Bridge:
        def start_search(self, payload): return {'status':'complete','session_id':'s','candidates':[]}
        def search(self, payload): return self.start_search(payload)
        def download(self, payload): return {'status':'submitted','task_id':'t'}
        def status(self, task_id): return {'status':'submitted','task_id':task_id}
        def close(self): pass

    with tempfile.TemporaryDirectory() as temp:
        secret = Path(temp)/'token'
        secret.write_text('smoke-token'); secret.chmod(0o600)
        settings = ConnectionSettings('http://moviepilot.invalid', str(secret), str(secret), public_hosts=('testserver', 'localhost', '127.0.0.1'))
        def lost_response(request):
            raise httpx.ReadError('protected URL must not leak', request=request)
        for transport in (httpx.MockTransport(lost_response),
                          httpx.MockTransport(lambda request: httpx.Response(502))):
            bridge = BridgeClient(settings, transport)
            result = bridge.download({'title':'Movie', 'request_id':'lost-response'})
            assert result['status'] == 'pending' and result['task_id'] == 'lost-response'
            assert 'protected URL' not in str(result)
            bridge.close()
        with TestClient(create_app(settings, Bridge())) as web:
            assert web.post('/api/search', json={'title':'Movie'}).status_code == 401
            assert web.post('/api/session', json={'token':'smoke-token'}).status_code == 200
            assert web.post('/api/download', json={'title':'Movie'}).status_code == 403
            assert web.post('/api/search', json={'title':'Movie'}, headers={'X-Media-Request':'1'}).status_code == 200
            assert web.get('/').status_code == 200
        server = create_server(Bridge())
        async def mcp_smoke():
            async with Client(server) as client:
                result = await client.list_tools()
                tools = {t.name: t for t in result.tools}
                assert set(tools) == {'search_resources','download_media','check_media','get_download_status'}
                assert {k: v for k, v in tools['check_media'].input_schema.items() if k != 'title'} == {
                    k: v for k, v in tools['download_media'].input_schema.items() if k != 'title'}
                assert tools['check_media'].annotations == tools['download_media'].annotations
                result = await client.call_tool('download_media', {'request': {'title':'Movie'}})
                assert result.structured_content['status'] == 'submitted', result
                result = await client.call_tool('check_media', {'request': {'candidate_id':'candidate'}})
                assert result.structured_content['status'] == 'submitted', result
                result = await client.call_tool('get_download_status', {'task_id':'t'})
                assert result.structured_content['task_id'] == 't'
        asyncio.run(mcp_smoke())
        with TestClient(create_http_app(server, settings)) as http:
            assert http.post('/mcp', json={}).status_code == 401
            # Standard HTTP discovery proves the endpoint is an MCP server, not a JSON shim.
            reply = http.post('/mcp', json={'jsonrpc':'2.0','id':1,'method':'tools/list',
                'params':{}, '_meta':{'io.modelcontextprotocol/protocolVersion':'2026-07-28'}},
                headers={'Authorization':'Bearer smoke-token', 'Accept':'application/json, text/event-stream'})
            assert reply.status_code == 200, reply.text
            assert all(name in reply.text for name in ('search_resources','download_media','check_media','get_download_status')), reply.text
    print('acquisition smoke: scopes, profiles, lazy search, deduplication, uncertain receipt, web and MCP OK')


if __name__ == '__main__':
    main()
