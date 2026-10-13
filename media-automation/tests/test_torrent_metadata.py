import bencode
import pytest

from app.plugins.filmwatchlist.evidence import torrent_evidence
from app.plugins.filmwatchlist.public_index import parse_torrent
from app.plugins.filmwatchlist.torrent_metadata import parse_metadata


@pytest.mark.parametrize('private', [0, 1])
def test_preview_and_submit_share_hash_files_and_private_flag(private):
    content = bencode.bencode({b'info': {b'name': b'Film', b'private': private,
        b'files': [{b'path': [b'legacy.mkv'], b'path.utf-8': ['电影.mkv'.encode()], b'length': 123},
                   {b'path': [b'extra.txt'], b'length': 4}]}})
    preview = parse_torrent(content)
    evidence = torrent_evidence(content, 'Film.1080p')
    assert preview == (evidence.info_hash, evidence.files, evidence.private)
    assert preview[1] == ('电影.mkv', 'extra.txt')
    assert evidence.video_bytes == 123 and evidence.total_bytes == 127


def test_preview_keeps_policy_separate_from_playability_validation():
    content = bencode.bencode({b'info': {b'name': b'Film.iso', b'length': 123}})
    assert parse_torrent(content)[1] == ('Film.iso',)
    with pytest.raises(ValueError):
        torrent_evidence(content, 'Film.ISO')


@pytest.mark.parametrize('root', [[], {}, {b'info': []}, {b'info': {b'files': []}},
                                 {b'info': {b'files': [1]}},
                                 {b'info': {b'files': [{b'length': 1}]}}])
def test_malformed_metadata_rejected(root):
    with pytest.raises(ValueError):
        parse_metadata(bencode.bencode(root))
