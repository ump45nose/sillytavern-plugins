"""One PT submit and hash deduplication through the old plugin entrypoint."""
from types import SimpleNamespace
from unittest.mock import patch

from app.plugins.filmwatchlist import FilmWatchlist

plugin = FilmWatchlist()
records = {}
decision = {'title': 'Movie', 'info_hash': 'a' * 40}
with patch('app.chain.download.DownloadChain') as chain:
    chain.return_value.download_single.return_value = ('a' * 40, None)
    plugin._submit_pt(1, SimpleNamespace(), b'content', decision, records)
    assert records['1']['task_state'] == 'SUBMITTED'
    plugin._submit_pt(2, SimpleNamespace(), b'content', decision, records)
    assert chain.return_value.download_single.call_count == 1
print('legacy PT submission smoke: OK')
