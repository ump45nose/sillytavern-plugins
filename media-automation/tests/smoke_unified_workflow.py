"""One dry-run and one mocked submit through the unified decision path."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import bencode

from app.plugins.filmwatchlist import FilmWatchlist
from app.plugins.filmwatchlist.public_index import (
    DownloadLink, IndexCandidate, IndexStatus, ResolvedCandidate,
)
from app.schemas.types import MediaType


def torrent(size: int) -> bytes:
    return bencode.bencode({b'info': {b'name': b'Movie.2025.2160p.Remux.mkv',
                                      b'length': size, b'private': 0}})


gib = 1024 ** 3
public_content, pt_content = torrent(100 * gib), torrent(108 * gib)
indexed = IndexCandidate('public-id', 'mini4k', 'Movie.2025.2160p.Remux',
                         'https://mini4k.io/movies/1', 'https://mini4k.io/torrents/1',
                         100 * gib, 'movie', '', 'unresolved', 'exact')
resolved = ResolvedCandidate(IndexStatus.OK, 'public-id',
                             (DownloadLink('torrent', torrent_bytes=public_content),))
context = SimpleNamespace(torrent_info=SimpleNamespace(
    site=1, category=MediaType.MOVIE.value, title='Movie.2025.2160p.Remux',
    seeders=5, page_url='https://m-team.test/1'))
media = SimpleNamespace(original_title='Movie', names=[], tmdb_id=123)
plugin = FilmWatchlist()
records = {}
common = {'title': 'Movie', 'media_key': '电影:123:S00',
          'media_type': MediaType.MOVIE.value, 'season': None,
          'tmdb_id': 123, 'douban_id': None}
downloader = Mock()
downloader.download_torrent.return_value = (pt_content, '', ['Movie.2025.2160p.Remux.mkv'])


def store(target, film_id, **values):
    target[str(film_id)] = {**target.get(str(film_id), {}), **values}


class Fake115:
    def target_path(self, media_type):
        assert media_type == MediaType.MOVIE.value
        return '/Media/Movie'

    def validate_target(self, media_type):
        self.target_path(media_type)

    def offline_task(self, info_hash):
        return None

    def submit_magnet(self, link, media_type):
        assert link.startswith('magnet:?xt=urn:btih:')
        self.target_path(media_type)
        return True


with patch.object(plugin, '_search_public', return_value=(IndexStatus.OK, [indexed], '')), \
        patch.object(plugin, '_indexer', return_value=SimpleNamespace(resolve=lambda _: resolved)), \
        patch.object(plugin, '_p115', return_value=Fake115()), \
        patch.object(plugin, '_store', side_effect=store), \
        patch('app.plugins.filmwatchlist.workflow.SearchChain') as search_chain, \
        patch('app.plugins.filmwatchlist.workflow.DownloadChain', return_value=downloader):
    search_chain.return_value.process.return_value = [context]
    plugin._dry_run = True
    plugin._process_unified(7, {'title': 'Movie', 'release_year': 2025}, media,
                            MediaType.MOVIE.value, None, common, records)
    assert records['7']['route'] == 'public_bt'
    assert records['7']['status'] == '预览'
    plugin._dry_run = False
    from host_stub import PluginManager
    host = PluginManager.registry['MediaCapabilities']
    host.init_plugin({**host.config, 'p115_route_enabled': True})
    plugin._process_unified(7, {'title': 'Movie', 'release_year': 2025}, media,
                            MediaType.MOVIE.value, None, common, records)
    assert records['7']['status'] == '115 下载中'
    assert records['7']['task_state'] == 'SUBMITTED'
    downloader.download_single.assert_not_called()

    host.init_plugin({**host.config, 'public_only': True})
    search_chain.reset_mock()
    plugin._dry_run = True
    plugin._process_unified(8, {'title': 'Movie', 'release_year': 2025}, media,
                            MediaType.MOVIE.value, None, common, records)
    assert records['8']['route'] == 'public_bt'
    search_chain.assert_not_called()
    before = host.runtime.registry.store.read()
    plugin._dry_run = False
    plugin._submit_pt(9, context, pt_content, {**common, 'info_hash': 'b'*40}, records)
    assert records['9']['status'] == '路由暂停' and records['9']['task_state'] == ''
    assert host.runtime.registry.store.read() == before
    downloader.download_single.assert_not_called()

    # The host setting overrides the watchlist's legacy PT-only branch.
    plugin._public_selection_enabled = False
    plugin._dry_run = True
    media.type, media.douban_id = MediaType.MOVIE, None
    with patch.object(plugin, '_resume_record', return_value=False), \
         patch.object(plugin, '_identify', return_value=(media, None, None)), \
         patch.object(plugin, '_library_complete', return_value=False), \
         patch.object(plugin, '_other_download', return_value=False), \
         patch.object(plugin, '_expected_episodes', return_value=None), \
         patch.object(plugin, '_media_snapshot', return_value={}), \
         patch.object(plugin, '_source_snapshot', return_value={}), \
         patch.object(plugin, '_process_unified') as unified:
        plugin._process_one({'id': 10, 'title': 'Movie'}, None, {})
        unified.assert_called_once()
        search_chain.assert_not_called()

# More than eight 2160p WEB results must not hide a higher-tier 1080p BluRay.
bluray = IndexCandidate('bluray-id', 'mini4k', 'Movie.2025.1080p.BluRay',
                        'https://mini4k.io/movies/1', 'https://mini4k.io/torrents/2',
                        10 * gib, 'movie', '', 'unresolved', 'exact')
webs = [IndexCandidate(f'web-{n}', 'mini4k', 'Movie.2025.2160p.WEB-DL',
                      'https://mini4k.io/movies/1', f'https://mini4k.io/torrents/{n+3}',
                      20 * gib, 'movie', '', 'unresolved', 'exact') for n in range(9)]
inspected = []


def resolve_ordered(candidate_id):
    inspected.append(candidate_id)
    return ResolvedCandidate(IndexStatus.OK, candidate_id,
                             (DownloadLink('torrent', torrent_bytes=torrent(10 * gib)),))


with patch.object(plugin, '_search_public', return_value=(IndexStatus.OK, [*webs, bluray], '')), \
     patch.object(plugin, '_indexer', return_value=SimpleNamespace(resolve=resolve_ordered)), \
     patch.object(plugin, '_p115', return_value=Fake115()), \
     patch.object(plugin, '_store', side_effect=store):
    plugin._dry_run = True
    plugin._process_unified(11, {'title': 'Movie', 'release_year': 2025}, media,
                            MediaType.MOVIE.value, None, common, records)
    assert inspected[0] == 'bluray-id'
    assert len(inspected) == 8
    assert records['11']['status'] == '预览'
    assert records['11']['candidate_id'] == 'bluray-id'
    downloader.download_single.assert_not_called()

print('unified workflow smoke: OK')
