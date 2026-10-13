"""Independent host, one-time migration and shared submission smoke; no live I/O."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from mcp import Client

from host_stub import PluginBase, PluginManager, load_plugin
from smoke_acquisition import Source, Identity, GIB
from media_capabilities.acquisition.client import BridgeClient, ConnectionSettings
from media_capabilities.acquisition.runtime import HostUnavailable
from media_search.app import create_app
from media_download_mcp.server import create_server


def main():
    assert 'app.plugins.filmwatchlist' not in sys.modules
    PluginBase.configs['FilmWatchlist'] = {'enabled': True, 'site_id': 3,
        'near_size_ratio': .12, 'p115_route_enabled': True, 'balanced_movie_gib': 42}
    PluginBase.data_by_id['FilmWatchlist'] = {
        'acquisition_v1': {'jobs': {'old-request': {'task_id': 'old-request', 'status': 'pending',
            'phase': 'submitting', 'route': 'pt', 'info_hash': 'a'*40}},
            'resources': {'a'*40: 'old-request'}},
        'records': {'9': {'route': '115_share', 'candidate_id': 'mini4k:v2:mini4k.io:torrents:9:-',
            'task_state': 'SUBMITTING', 'media_type': 'movie', 'target_path': '/Media/Movie'}},
    }
    original = deepcopy(PluginBase.data_by_id['FilmWatchlist'])
    Host = load_plugin('mediacapabilities', 'MediaCapabilities')
    host = Host()
    host.init_plugin({'site_id': 7, 'balanced_movie_gib': 30})
    assert not host.error and not host.get_state(), host.error
    assert host.config['site_id'] == 7 and host.config['balanced_movie_gib'] == 30
    assert host.config['near_size_ratio'] == .12 and host.config['p115_route_enabled']
    assert host.acquisition_download({'title': 'Movie'})['status'] == 'unavailable'
    registry = host.runtime.registry
    first_state = registry.store.read()
    host.init_plugin(host.config)
    assert registry.store.read() == first_state
    assert PluginBase.data_by_id['FilmWatchlist'] == original
    assert all(api['auth'] == 'bear' for api in host.get_api()) and len(host.get_api()) == 5
    inherited = registry.submit('share-retry', 'share-link-hash',
        {'route': '115_share', 'candidate_id': original['records']['9']['candidate_id']},
        lambda: (_ for _ in ()).throw(AssertionError('migration re-submitted share')))
    assert inherited['status'] == 'pending' and inherited['reused']

    class Provider:
        calls = 0
        uncertain = False
        size = 25*GIB

    class Downloader:
        def __init__(self, factory, authorize):
            self.guard_submission = authorize
        def submit(self, candidate, target):
            Provider.calls += 1
            assert any(row.get('phase') == 'submitting' for row in registry.store.read()['jobs'].values())
            if Provider.uncertain:
                raise TimeoutError('secret must not reach a receipt')
            return {'status': 'submitted'} if candidate.public else {
                'status': 'submitted', 'download_hash': candidate.info_hash}
        def status(self, record):
            return {}

    with patch('media_capabilities.acquisition.runtime.MoviePilotIdentity', Identity), \
         patch('media_capabilities.acquisition.runtime.MTeamAdapter',
               side_effect=lambda settings, identities: Source('mteam', [('Movie.2160p.Remux', Provider.size+GIB)])), \
         patch('media_capabilities.acquisition.runtime.Mini4KAdapter',
               side_effect=lambda settings, indexer, factory: Source('mini4k', [('Movie.2160p.Remux', Provider.size)])), \
         patch('media_capabilities.acquisition.runtime.MoviePilotDownloadAdapter', Downloader):
        host.init_plugin({**host.config, 'enabled': True})
        PluginManager.registry['MediaCapabilities'] = host
        owner = [host]
        assert host.runtime.registry is registry

        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory)/'token'
            token.write_text('host-smoke-token'); token.chmod(0o600)
            settings = ConnectionSettings('http://moviepilot.invalid', str(token), str(token),
                                          public_hosts=('testserver',))
            def handler(request):
                prefix = '/api/v1/plugin/MediaCapabilities/acquisition_'
                assert request.url.path.startswith(prefix) and request.headers['Authorization'] == 'Bearer host-smoke-token'
                operation = request.url.path.removeprefix(prefix)
                payload = json.loads(request.content) if request.content else {}
                args = request.url.params
                result = {'search': lambda: owner[0].acquisition_search(payload),
                    'search_status': lambda: owner[0].acquisition_search_status(args['session_id']),
                    'more': lambda: owner[0].acquisition_more(payload),
                    'download': lambda: owner[0].acquisition_download(payload),
                    'status': lambda: owner[0].acquisition_status(args['task_id'])}[operation]()
                return httpx.Response(200, json=result)
            def bridge():
                return BridgeClient(settings, httpx.MockTransport(handler))

            query = bridge()
            result = query.search({'title': 'Movie'}, wait=2)
            assert len(result['candidates']) == 2 and Provider.calls == 0
            assert all(source.inspections == 0 for source in host.runtime.execution().sources.values())
            assert 'app.plugins.filmwatchlist' not in sys.modules

            mcp_bridge = bridge()
            async def mcp_call():
                async with Client(create_server(mcp_bridge)) as client:
                    assert len((await client.list_tools()).tools) == 3
                    result = await client.call_tool('download_media', {'request': {'title': 'Movie', 'request_id': 'mcp'}})
                    receipt = result.structured_content
                    assert receipt['status'] == 'submitted' and receipt['route'] == 'public_bt'
                    status = await client.call_tool('get_download_status', {'task_id': receipt['task_id']})
                    assert status.structured_content['status'] == 'submitted'
                    return receipt
            receipt = asyncio.run(mcp_call())
            with TestClient(create_app(settings, bridge())) as web:
                assert web.post('/api/download', json={'title': 'Movie'}).status_code == 401
                web.post('/api/session', json={'token': 'host-smoke-token'})
                result = web.post('/api/download', json={'title': 'Movie', 'request_id': 'web'},
                                  headers={'X-Media-Request': '1'}).json()
                assert result['reused'] and result['route'] == 'public_bt'
            assert Provider.calls == 1 and 'app.plugins.filmwatchlist' not in sys.modules

            Film = load_plugin('filmwatchlist', 'FilmWatchlist')
            film, records = Film(), {}
            with patch('app.chain.download.DownloadChain') as chain:
                film._submit_pt(10, None, b'content', {'info_hash': receipt['info_hash']}, records)
                assert records['10']['route'] == 'public_bt' and records['10']['task_state'] == 'SUBMITTED'
                chain.assert_not_called()
            assert film._capabilities().registry is registry and Provider.calls == 1
            assert not any(api['path'].startswith('/acquisition_') for api in film.get_api())

            Provider.uncertain, Provider.size = True, 45*GIB
            old_runtime, browser_lock = host.runtime, host.runtime.navigation_lock
            host.init_plugin(host.config)
            pending = query.download({'title': 'Movie', 'request_id': 'uncertain'})
            assert pending['status'] == 'pending' and Provider.calls == 2
            host.stop_service()
            replacement = Host()
            replacement.init_plugin(host.config)
            owner[0] = replacement
            PluginManager.registry['MediaCapabilities'] = replacement
            assert replacement.runtime.registry is registry and replacement.runtime.navigation_lock is browser_lock
            assert query.status('uncertain')['status'] == 'pending'
            assert query.download({'title': 'Movie', 'request_id': 'after-reload'})['status'] == 'pending'
            assert Provider.calls == 2
            try:
                old_runtime.submit_pt('closed', 'f'*40, None, b'content')
                raise AssertionError('old runtime submitted after reload')
            except HostUnavailable:
                pass
            replacement.init_plugin({**replacement.config, 'enabled': False})
            assert query.status('uncertain')['status'] == 'pending'
            assert query.download({'title': 'Movie', 'request_id': 'disabled'})['status'] == 'unavailable'
            assert Provider.calls == 2
            query.close(); mcp_bridge.close(); replacement.stop_service()
    print('independent host smoke: migration, both apps without FilmWatchlist, shared receipts and reload OK')


if __name__ == '__main__':
    main()
