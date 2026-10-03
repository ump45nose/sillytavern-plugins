"""Small, side-effect-free quality and 115 routing smoke check."""

import bencode

from app.plugins.filmwatchlist.evidence import torrent_evidence, magnet_hash
from app.plugins.filmwatchlist.quality_selection import MediaCandidate, rank_candidates
from app.plugins.filmwatchlist.p115_task_adapter import P115TaskAdapter


def torrent(name: bytes, size: int, private: int = 0) -> bytes:
    return bencode.bencode({b'info': {b'name': name, b'length': size,
                                      b'private': private}})


evidence = torrent_evidence(torrent(b'Movie.2025.2160p.Remux.mkv', 1000),
                            'Movie.2025.2160p.Remux')
assert evidence.video_bytes == 1000 and not evidence.private
assert torrent_evidence(torrent(b'Movie.2025.2160p.Remux.mkv', 1000, 1),
                        'Movie.2025.2160p.Remux').private
try:
    torrent_evidence(torrent(b'Movie.iso', 1000), 'Movie.2160p.ISO')
    raise AssertionError('disc was accepted')
except ValueError:
    pass

public = MediaCandidate('public_bt', 'Movie.2160p.Remux', 100, 100, 'public')
pt_close = MediaCandidate('pt', 'Movie.2160p.Remux', 108, 108, 'pt')
pt_large = MediaCandidate('pt', 'Movie.2160p.Remux', 125, 125, 'pt')
encoded = MediaCandidate('pt', 'Movie.2160p.BluRay.x265', 500, 500, 'encoded')
assert rank_candidates([public, pt_close])[0].source == 'public_bt'
assert rank_candidates([public, pt_large])[0].candidate_id == 'pt'
assert rank_candidates([public, encoded])[0].candidate_id == 'public'
assert magnet_hash('magnet:?xt=urn:btih:' + 'A' * 40) == 'a' * 40

adapter = P115TaskAdapter()
assert adapter.target_path('movie') == '/Media/Movie'
assert adapter.target_path('tv_show') == '/Media/TV_Show'
print('quality and 115 routing smoke: OK')
