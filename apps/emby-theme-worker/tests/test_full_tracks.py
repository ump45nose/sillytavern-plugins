import shutil
import subprocess
from types import SimpleNamespace

import pytest

from emby_theme_worker.audio import AudioProcessor
from emby_theme_worker.config import Config
from emby_theme_worker.db import StateDB
from emby_theme_worker.models import Candidate, MediaItem
from emby_theme_worker.studio import Studio
from emby_theme_worker.worker import Worker


@pytest.fixture
def full_track(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg required for audio smoke')
    source = tmp_path/'song.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=70', str(source)], check=True)
    return source


def test_online_track_keeps_full_length(full_track, tmp_path):
    audio = AudioProcessor(45, '192k', 30, {})
    target = tmp_path/'full.mp3'
    selection = audio.normalize_online(full_track, target)
    assert selection['mode'] == 'full'
    assert audio.validate_full(target, expected_duration=70)['duration'] == pytest.approx(70, abs=.1)


def test_upload_full_and_explicit_trim(full_track, tmp_path):
    config = Config(database_path=str(tmp_path/'worker.db'), staging_path=str(tmp_path/'staging'), allowed_path=str(tmp_path))
    db = StateDB(config.database_path); db.initialize()
    studio = Studio(config, db)
    item = MediaItem('1', 'Movie', None, 2000, 'Movie', str(tmp_path))
    worker = SimpleNamespace(audio=AudioProcessor(45, '192k', 30, {}), emby=SimpleNamespace(get_item=lambda _: item, refresh_and_verify=lambda *a, **kw: True))
    uploaded = studio.upload('1', full_track.read_bytes())
    result = studio.execute(worker, 'prepare', '1', {'asset_id': uploaded})
    assert result['mode'] == 'full' and result['info']['duration'] > 69
    trimmed = studio.execute(worker, 'trim', '1', {'asset_id': result['asset_id'], 'basis': 'prepared', 'start': 10, 'end': 50})
    assert trimmed['mode'] == 'trimmed'
    assert trimmed['info']['duration'] == pytest.approx(40, abs=.1)
    assert result['info']['sha256'] == worker.audio.validate_full(studio.asset(result['asset_id'])/'prepared.mp3')['sha256']
    for start, end in [(0, 500), (float('nan'), 30), (10, float('inf'))]:
        with pytest.raises(ValueError, match='invalid selection'):
            studio.execute(worker, 'trim', '1', {'asset_id': result['asset_id'], 'start': start, 'end': end})
    # A legacy clipped preview is expanded from the retained source, not the clip.
    legacy = studio.asset(uploaded)
    (legacy/'prepared.mp3').write_bytes((studio.asset(trimmed['asset_id'])/'prepared.mp3').read_bytes())
    expanded = studio.execute(worker, 'prepare', '1', {'asset_id': uploaded})
    assert expanded['info']['duration'] > 69
    assert studio.execute(worker, 'apply', '1', {'asset_id': expanded['asset_id']})['locked']
    assert worker.audio.validate_full(tmp_path/'theme.mp3')['duration'] > 69


def test_automatic_commit_accepts_complete_song(full_track, tmp_path):
    worker = object.__new__(Worker)
    worker.audio = AudioProcessor(45, '192k', 30, {})
    worker._fetch_candidate = lambda *args: full_track
    worker.db = SimpleNamespace(diagnostic=lambda *a: None, set_control=lambda *a, **kw: None)
    committed = {}
    def commit(item, prepared, provider, transport, score, info):
        committed.update(info)
        return {'status': 'complete'}
    worker._commit = commit
    item = MediaItem('1', 'Movie', None, 2000, 'Movie', str(tmp_path))
    worker._from_candidate(item, Candidate('youtube', 'Main theme', 'https://example.test', score=90))
    assert committed['duration'] > 69
