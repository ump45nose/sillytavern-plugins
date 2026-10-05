"""在 MoviePilot 宿主解释器中模拟候选与媒体库状态，验证下载边界。"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import bencode

from app.plugins.filmwatchlist import FilmWatchlist
from app.schemas.types import MediaType


plugin = FilmWatchlist()
plugin._dry_run = False
media = SimpleNamespace(type=MediaType.MOVIE.value, tmdb_id=123, douban_id=None)
disc = SimpleNamespace(torrent_info=SimpleNamespace(
    site=1, category=MediaType.MOVIE.value, title="Film.2160p.BluRay.ISO", seeders=9,
    page_url="https://example.test/disc"))
fallback = SimpleNamespace(torrent_info=SimpleNamespace(
    site=1, category=MediaType.MOVIE.value, title="Film.2160p.WEB-DL", seeders=2,
    page_url="https://example.test/file"))
downloader = Mock()
downloader.download_torrent.side_effect = [
    (b"disc", "", ["Film.iso"]),
    (bencode.bencode({b'info': {b'name': b'Film.mkv', b'length': 1234}}), "", ["Film.mkv"]),
]
downloader.download_single.return_value = ("test-hash", None)
records = {}
marked = []


def record(target, film_id, **values):
    """用内存代替插件持久化，确保冒烟不会修改真实任务。"""
    target[str(film_id)] = {**target.get(str(film_id), {}), **values}


with patch.object(plugin, "_identify", return_value=(media, None, "")), \
        patch.object(plugin, "_library_complete", side_effect=[False, False, True]), \
        patch.object(plugin, "_task_present", return_value=True) as task_present, \
        patch.object(plugin, "_other_download", return_value=False), \
        patch.object(plugin, "_store", side_effect=record), \
        patch.object(plugin, "_writeback_record", side_effect=lambda client, film_id, record: (marked.append(film_id) or True, "完成")), \
        patch("app.plugins.filmwatchlist.workflow.SearchChain") as search_chain, \
        patch("app.plugins.filmwatchlist.workflow.DownloadChain", return_value=downloader), \
        patch("app.chain.download.DownloadChain", return_value=downloader):
    search_chain.return_value.process.return_value = [disc, fallback]
    item = {"id": 99, "title": "Film", "release_year": 2024}
    plugin._process_one(item, object(), records)
    assert records["99"]["download_hash"] == "test-hash"
    assert records["99"]["non_remux"] is True
    assert downloader.download_single.call_count == 1
    assert not marked

    plugin._process_one(item, object(), records)
    assert downloader.download_single.call_count == 1
    task_present.assert_called_once_with("test-hash")
    assert not marked

    plugin._process_one(item, object(), records)
    assert marked == [99]
    assert records["99"]["status"] == "已完成"

print("workflow smoke: OK")
