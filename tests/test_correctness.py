import base64
import json
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import bencode
import pytest

import app.plugins.filmwatchlist as fw
from app.plugins.filmwatchlist import observe, workflow
from app.plugins.filmwatchlist.p115_task_adapter import P115TaskAdapter
from app.plugins.filmwatchlist.public_index import (
    DownloadLink, IndexCandidate, IndexStatus, MediaQuery, Mini4KIndexer, ResolvedCandidate,
)
from app.schemas.types import MediaType
from host_stub import PluginBase, PluginManager


def torrent(size=100, name='Film.2024.1080p.Remux.mkv'):
    return bencode.bencode({b'info': {b'name': name.encode(), b'length': size, b'private': 0}})


def context(title='Film.2024.1080p.Remux', page='https://m-team.test/1'):
    return SimpleNamespace(torrent_info=SimpleNamespace(
        site=1, category=MediaType.MOVIE.value, title=title, seeders=1, page_url=page))


@pytest.fixture
def env(monkeypatch):
    for data in PluginBase.data_by_id.values():
        data.clear()
    PluginManager.registry['MediaCapabilities'].init_plugin({'enabled': True})
    plugin = fw.FilmWatchlist()
    plugin._enabled = True
    plugin._dry_run = False
    media = SimpleNamespace(type=MediaType.MOVIE, tmdb_id=123, douban_id=None,
                            title='Film', year='2024', original_title='Film', names=[])
    monkeypatch.setattr(plugin, '_identify', Mock(return_value=(media, None, '')))
    monkeypatch.setattr(plugin, '_library_complete', Mock(return_value=False))
    monkeypatch.setattr(plugin, '_other_download', Mock(return_value=False))
    monkeypatch.setattr(plugin, '_task_present', Mock(return_value=False))
    monkeypatch.setattr(plugin, '_client', Mock(return_value=Mock()))
    plugin._client.return_value.get_res.return_value = SimpleNamespace(status_code=200, json=item)
    monkeypatch.setattr(plugin, '_films', Mock(return_value=[]))
    monkeypatch.setattr(fw, 'SiteOper', Mock(return_value=SimpleNamespace(get=lambda _: None)))
    downloader = Mock()
    downloader.download_torrent.return_value = (torrent(), '', ['Film.mkv'])
    downloader.download_single.return_value = ('download-hash', None)
    monkeypatch.setattr(workflow, 'DownloadChain', Mock(return_value=downloader))
    monkeypatch.setattr(sys.modules['app.chain.download'], 'DownloadChain', Mock(return_value=downloader))
    search = Mock()
    search.process.return_value = [context(), context(page='https://m-team.test/2')]
    monkeypatch.setattr(workflow, 'SearchChain', Mock(return_value=search))
    return plugin, media, downloader, search


def item():
    return {'id': 7, 'title': 'Film', 'release_year': 2024}


def common():
    return {'title': 'Film', 'media_type': '电影', 'media_key': '电影:123:S00',
            'tmdb_id': 123, 'douban_id': None, 'season': None}


def pending(**extra):
    return {**common(), 'film_id': 7, 'task_state': 'SUBMITTING', 'route': 'pt',
            'info_hash': 'abc123', **extra}


def test_unified_pt_success_records_receipt(env, monkeypatch):
    plugin, media, download, _ = env
    monkeypatch.setattr(plugin, '_search_public', lambda _: (IndexStatus.NO_RESULTS, [], ''))
    records = {}
    plugin._process_unified(7, item(), media, '电影', None, common(), records)
    assert records['7']['download_hash'] == 'download-hash'
    assert records['7']['task_state'] == 'SUBMITTED'


def test_unified_share_success_records_roots(env, monkeypatch):
    plugin, media, download, search = env
    search.process.return_value = []
    host = PluginManager.registry['MediaCapabilities']
    host.init_plugin({**host.config, 'share_115_enabled': True, 'p115_route_enabled': True})
    candidate = IndexCandidate('id', 'mini4k', 'Film.1080p.Remux',
                               'https://mini4k.io/movies/1', 'https://mini4k.io/movies/1',
                               100, 'movie', '', '115_share', 'exact')
    monkeypatch.setattr(plugin, '_search_public', lambda _: (IndexStatus.OK, [candidate], ''))
    link = ResolvedCandidate(IndexStatus.OK, 'id', (DownloadLink('115_share', value='https://115.com/s/x'),))
    monkeypatch.setattr(plugin, '_indexer', lambda: SimpleNamespace(resolve=lambda _: link))
    adapter = Mock()
    adapter.preview_share.return_value = workflow.ShareEvidence(('Film.mkv',), 100, 100, (1,), ('Film.mkv',))
    adapter.target_path.return_value = '/Media/Movie'
    adapter.local_strm_root = '/Media/115_strm'
    adapter.cloud_items.return_value = []
    adapter.submit_share.return_value = True
    adapter.last_submission_receipt = None
    monkeypatch.setattr(plugin, '_p115', lambda *args: adapter)
    records = {}
    plugin._process_unified(7, item(), media, '电影', None, common(), records)
    assert records['7']['share_root_names'] == ['Film.mkv']
    assert records['7']['task_state'] == 'SUBMITTED'
    assert records['7']['status'] == '等待整理'
    assert 'https://115' not in json.dumps(records)


@pytest.mark.parametrize('result', [(None, 'rejected'), TimeoutError('response lost')])
def test_legacy_unknown_submission_never_tries_next_candidate(env, result):
    plugin, media, download, search = env
    if isinstance(result, Exception):
        download.download_single.side_effect = result
    else:
        download.download_single.return_value = result
    records = {}
    def submit(*args, **kwargs):
        assert plugin.data['records']['7']['task_state'] == 'SUBMITTING'
        assert plugin.data['records']['7']['info_hash']
        if isinstance(result, Exception):
            raise result
        return result
    download.download_single.side_effect = submit
    plugin._process_one(item(), object(), records)
    plugin._process_one(item(), object(), records)
    assert download.download_single.call_count == 1
    assert records['7']['status'] == '提交结果待核实'
    assert search.process.call_count == 1


def test_successful_submit_then_failed_local_write_remains_recoverable(env, monkeypatch):
    plugin, media, download, search = env
    original = plugin.save_data
    def save(key, data):
        if key == 'records' and data.get('7', {}).get('task_state') == 'SUBMITTED':
            raise OSError('disk unavailable')
        original(key, data)
    monkeypatch.setattr(plugin, 'save_data', save)
    with pytest.raises(OSError):
        plugin._process_one(item(), object(), {})
    assert plugin.data['records']['7']['task_state'] == 'SUBMITTING'
    monkeypatch.setattr(plugin, 'save_data', original)
    plugin._task_present.return_value = True
    plugin.run_once()
    assert download.download_single.call_count == 1
    assert plugin.data['records']['7']['task_state'] == 'SUBMITTED'


@pytest.mark.parametrize('scan_case', ['site_disabled', 'source_down', 'removed'])
def test_saved_115_task_recovers_independently_of_source_and_metadata(env, monkeypatch, scan_case):
    plugin, media, download, search = env
    old = pending(route='public_bt', target_path='/Media/OriginalMovie')
    plugin.save_data('records', {'7': old})
    plugin._identify.side_effect = AssertionError('must not re-identify')
    adapter = Mock()
    adapter.offline_task.return_value = {'status': 2, 'delete_file_id': '42'}
    adapter.ensure_strm.return_value = 1
    seen = []
    monkeypatch.setattr(plugin, '_p115', lambda record=None: (seen.append(record) or adapter))
    if scan_case != 'site_disabled':
        monkeypatch.setattr(fw, 'SiteOper', lambda: SimpleNamespace(
            get=lambda _: SimpleNamespace(is_active=True, domain='m-team.test', name='M-Team')))
    if scan_case == 'source_down':
        plugin._films.side_effect = TimeoutError()
    plugin.run_once()
    assert plugin.data['records']['7']['strm_ready'] is True
    assert seen[0]['target_path'] == '/Media/OriginalMovie'
    adapter.ensure_strm.assert_called_once_with('电影', (42,))
    plugin._identify.assert_not_called()
    download.download_single.assert_not_called()


def test_p115_recovery_freezes_original_target(env):
    plugin, *_ = env
    plugin._p115_movie_path = '/Media/NewMovie'
    adapter = plugin._p115(pending(route='public_bt', target_path='/Media/OldMovie',
                                  local_strm_root='/Media/old_strm'))
    assert adapter.target_path('电影') == '/Media/OldMovie'
    assert adapter.local_strm_root == '/Media/old_strm'


def test_frozen_identity_and_episodes_drive_library_check(env):
    plugin, *_ = env
    old = pending(media_type='电视剧', season=1, media_key='电视剧:123:S01',
                  media_snapshot={'title': 'Old', 'media_type': '电视剧', 'season': 1,
                                  'tmdb_id': 123, 'expected_episodes': [1, 2, 3]})
    plugin.save_data('records', {'7': old})
    plugin.run_once()
    checked, season = plugin._library_complete.call_args.args
    assert checked.title == 'Old' and checked.seasons == {1: [1, 2, 3]} and season == 1


def test_writeback_retry_uses_saved_library_completion_even_without_metadata(env):
    plugin, media, download, search = env
    plugin._client.return_value.request.return_value = None
    plugin.save_data('records', {'7': pending(library_ready=True, source_snapshot=plugin._source_snapshot(item()))})
    plugin.run_once()
    assert plugin.data['records']['7']['status'] == '待写回'
    plugin._client.return_value.request.return_value = SimpleNamespace(status_code=200)
    plugin.run_once()
    assert plugin.data['records']['7']['status'] == '已完成'
    plugin._library_complete.assert_not_called()
    plugin._identify.assert_not_called()
    download.download_single.assert_not_called()


def test_legacy_download_hash_recovers(env):
    plugin, *_ = env
    old = {**common(), 'download_hash': 'legacy-hash', 'status': '等待入库'}
    plugin.save_data('records', {'7': old})
    plugin.run_once()
    plugin._task_present.assert_called_once_with('legacy-hash')


def test_same_media_other_film_blocks_legacy_submit(env):
    plugin, _, download, search = env
    records = {'6': pending(film_id=6)}
    plugin._process_one(item(), object(), records)
    search.process.assert_not_called()
    download.download_single.assert_not_called()


@pytest.mark.parametrize('kind,folder', [('movie', 'Movie'), ('电影', 'Movie'),
    (MediaType.MOVIE, 'Movie'), ('tv', 'TV_Show'), ('tv_show', 'TV_Show'),
    ('电视剧', 'TV_Show'), (MediaType.TV, 'TV_Show')])
def test_strm_and_cloud_media_type_mapping(kind, folder, tmp_path, monkeypatch):
    import conftest
    captured = []
    class Api:
        def __init__(self, **kwargs): pass
        def api_strm_sync_creata(self, payload):
            captured.extend(payload.data)
            return SimpleNamespace(code=0, data=SimpleNamespace(success_count=1))
    conftest.module('p115client')
    conftest.module('p115client.tool')
    conftest.module('p115client.tool.attr', get_attr=lambda *a, **k: {'id': 1, 'name': 'Film.mkv'})
    conftest.module('p115client.tool.iterdir', iter_files_with_path_skim=Mock())
    conftest.module('app.plugins.p115strmhelper')
    conftest.module('app.plugins.p115strmhelper.api', Api=Api)
    conftest.module('app.plugins.p115strmhelper.schemas')
    conftest.module('app.plugins.p115strmhelper.schemas.strm_api',
                    StrmApiData=SimpleNamespace, StrmApiPayloadData=SimpleNamespace)
    adapter = P115TaskAdapter(local_strm_root=str(tmp_path))
    monkeypatch.setattr(adapter, '_service', lambda: SimpleNamespace(client=object()))
    assert adapter.ensure_strm(kind, (1,)) == 1
    assert captured[0].local_path == str(tmp_path / folder)
    assert captured[0].pan_media_path == '/Media/' + folder


def test_unknown_media_type_rejects_before_strm_io(tmp_path):
    adapter = P115TaskAdapter(local_strm_root=str(tmp_path))
    with pytest.raises(ValueError):
        adapter.ensure_strm('documentary', ())
    assert list(tmp_path.iterdir()) == []


class Browser:
    def __init__(self, html): self.html = html
    @contextmanager
    def open(self): yield self
    def goto(self, url): return self.html


def test_candidate_ids_are_safe_stable_and_resolve_after_restart():
    url = 'https://mini4k.io/movies/1?private=query'
    link = 'https://115.com/s/secretShare?password=privateCode#secret'
    cid = Mini4KIndexer._candidate_id(url, link)
    assert all(secret not in cid for secret in ('secretShare', 'privateCode', 'password', 'query'))
    assert cid == Mini4KIndexer._candidate_id(url, link.replace('privateCode', 'newCode'))
    current = link.replace('privateCode', 'newCode')
    result = Mini4KIndexer(Browser(f'<a href="{current}">115</a>')).resolve(cid)
    assert result.status == IndexStatus.OK
    assert result.links[0].value == current


def test_legacy_candidate_still_resolves_without_rekeying():
    resource, link = 'https://mini4k.io/movies/1', 'https://115.com/s/old?password=legacy'
    cid = 'mini4k:' + base64.urlsafe_b64encode(json.dumps([resource, link]).encode()).decode().rstrip('=')
    result = Mini4KIndexer(Browser(f'<a href="{link}">115</a>')).resolve(cid)
    assert result.status == IndexStatus.OK and result.candidate_id == cid
    assert Mini4KIndexer.comparable_candidate_id(cid) == Mini4KIndexer._candidate_id(resource, link)


def test_legacy_tv_enriches_by_saved_id_without_source_search(env, monkeypatch):
    plugin, *_ = env
    old = pending(media_type='电视剧', season=1, route='public_bt')
    plugin.save_data('records', {'7': old})
    chain = Mock()
    chain.recognize_media.return_value = SimpleNamespace(type=MediaType.TV, tmdb_id=123,
                                                          douban_id=None, seasons={1: [1, 2]})
    monkeypatch.setattr(observe, 'MediaChain', lambda: chain)
    adapter = Mock()
    adapter.offline_task.return_value = {'status': 0}
    monkeypatch.setattr(plugin, '_p115', lambda *args: adapter)
    plugin.run_once()
    assert plugin.data['records']['7']['media_snapshot']['expected_episodes'] == [1, 2]
    chain.recognize_media.assert_called_once_with(mtype=MediaType.TV, tmdbid=123, doubanid=None)
    plugin._identify.assert_not_called()


def test_legacy_tv_metadata_failure_does_not_block_strm(env, monkeypatch):
    plugin, *_ = env
    plugin.save_data('records', {'7': pending(media_type='电视剧', season=1, route='public_bt')})
    chain = Mock()
    chain.recognize_media.side_effect = TimeoutError()
    monkeypatch.setattr(observe, 'MediaChain', lambda: chain)
    adapter = Mock()
    adapter.offline_task.return_value = {'status': 2, 'delete_file_id': '42'}
    adapter.ensure_strm.return_value = 1
    monkeypatch.setattr(plugin, '_p115', lambda *args: adapter)
    plugin.run_once()
    assert plugin.data['records']['7']['strm_ready'] is True
    adapter.ensure_strm.assert_called_once_with('电视剧', (42,))


def test_intent_persistence_failure_prevents_external_submit(env, monkeypatch):
    plugin, _, download, _ = env
    monkeypatch.setattr(plugin, 'save_data', Mock(side_effect=OSError('disk unavailable')))
    with pytest.raises(OSError):
        plugin._process_one(item(), object(), {})
    download.download_single.assert_not_called()


def test_completed_source_reopened_same_identity_checks_library_and_writes_back(env):
    plugin, media, download, search = env
    records = {'7': pending(status='已完成', library_ready=True, task_state='SUBMITTED')}
    plugin._library_complete.return_value = True
    plugin._client.return_value.request.return_value = SimpleNamespace(status_code=200)
    plugin._process_one(item(), plugin._client(), records)
    plugin._identify.assert_called_once()
    plugin._library_complete.assert_called_once_with(media, None)
    plugin._client.return_value.request.assert_called_once()
    assert records['7']['status'] == '已完成'
    download.download_single.assert_not_called()


def test_completed_source_corrected_identity_archives_old_receipt_and_clears_library_fact(env):
    plugin, media, download, search = env
    old = pending(status='已完成', task_state='SUBMITTED', download_hash='old-hash', library_ready=True)
    records = {'7': old}
    media.tmdb_id = 456
    plugin._process_one(item(), plugin._client(), records)
    assert records['7']['media_key'] == '电影:456:S00'
    assert records['7']['library_ready'] is False
    assert records['7']['download_hash'] == 'download-hash'
    assert records['7']['completed_history'] == [old]
    plugin._client.return_value.request.assert_not_called()
    assert download.download_single.call_count == 1


def test_reopened_completed_media_without_library_never_blindly_resubmits(env):
    plugin, media, download, search = env
    records = {'7': pending(status='已完成', library_ready=True, download_hash='old-hash')}
    plugin._process_one(item(), plugin._client(), records)
    assert records['7']['status'] == '等待入库'
    plugin._task_present.assert_called_once_with('old-hash')
    plugin._client.return_value.request.assert_not_called()
    download.download_single.assert_not_called()
    assert records['7']['library_ready'] is False
    plugin._process_one(item(), plugin._client(), records)
    plugin._client.return_value.request.assert_not_called()


def test_inflight_identity_change_never_marks_different_source_downloaded(env):
    plugin, media, download, _ = env
    old = pending(library_ready=True, source_snapshot=plugin._source_snapshot(item()))
    plugin.save_data('records', {'7': old})
    plugin._client.return_value.get_res.return_value = SimpleNamespace(
        status_code=200, json=lambda: {**item(), 'release_year': 2025})
    media.tmdb_id = 456
    plugin.run_once()
    assert plugin.data['records']['7']['library_ready'] is True
    assert plugin.data['records']['7']['status'] == '待写回'
    assert '身份已改变' in plugin.data['records']['7']['reason']
    plugin._client.return_value.request.assert_not_called()
    download.download_single.assert_not_called()


def test_aliased_source_same_identity_can_writeback_without_new_metadata(env):
    plugin, media, download, _ = env
    old = pending(library_ready=True, source_snapshot=plugin._source_snapshot(item()))
    plugin.save_data('records', {'7': old})
    plugin._client.return_value.get_res.return_value = SimpleNamespace(
        status_code=200, json=lambda: {**item(), 'id': 99})
    plugin._client.return_value.request.return_value = SimpleNamespace(status_code=200)
    plugin.run_once()
    assert plugin.data['records']['7']['status'] == '已完成'
    plugin._identify.assert_not_called()
    plugin._client.return_value.request.assert_called_once_with(
        'PATCH', plugin._api_url + '/v1/films/7/downloaded', json={'downloaded': True})


def test_source_detail_outage_only_blocks_writeback(env):
    plugin, media, download, _ = env
    plugin.save_data('records', {'7': pending(library_ready=True)})
    plugin._client.return_value.get_res.side_effect = TimeoutError()
    plugin.run_once()
    assert plugin.data['records']['7']['status'] == '待写回'
    assert plugin.data['records']['7']['library_ready'] is True
    plugin._client.return_value.request.assert_not_called()
    download.download_single.assert_not_called()


def test_library_only_completion_reopened_clears_old_fact_before_new_submit(env):
    plugin, media, download, _ = env
    records = {'7': {**common(), 'status': '已完成', 'library_ready': True}}
    plugin._process_one(item(), plugin._client(), records)
    assert records['7']['download_hash'] == 'download-hash'
    assert records['7']['library_ready'] is False
    plugin._process_one(item(), plugin._client(), records)
    plugin._client.return_value.request.assert_not_called()
    assert download.download_single.call_count == 1


@pytest.mark.parametrize('script', ['smoke_selection.py', 'smoke_public_index.py',
    'smoke_quality_115.py', 'smoke_identify_retry.py',
    'smoke_unified_workflow.py', 'smoke_workflow.py'])
def test_existing_offline_smokes(script):
    runpy.run_path(str(Path(__file__).with_name(script)), run_name='__main__')
