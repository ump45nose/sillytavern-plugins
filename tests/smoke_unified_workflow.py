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
plugin._site_id = 1
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
    plugin._p115_route_enabled = True
    plugin._process_unified(7, {'title': 'Movie', 'release_year': 2025}, media,
                            MediaType.MOVIE.value, None, common, records)
    assert records['7']['status'] == '115 下载中'
    assert records['7']['task_state'] == 'SUBMITTED'
    downloader.download_single.assert_not_called()

print('unified workflow smoke: OK')
