"""Offline regressions for replacement adoption, Emby refresh and media budgets."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from emby_theme_worker.audio import AudioProcessor, sha256
from emby_theme_worker.config import Config
from emby_theme_worker.db import StateDB
from emby_theme_worker.emby import EmbyClient
from emby_theme_worker.media_limits import AudioSizeLimitError, MAX_AUDIO_BYTES
from emby_theme_worker.models import MediaItem
from emby_theme_worker.studio import Studio


@pytest.mark.parametrize('status,existing', [('skipped_existing', True), ('skipped_existing_unindexed', True), ('failed', False)])
def test_manual_apply_after_null_provider(tmp_path, status, existing):
    item = MediaItem('1', 'Movie', None, 2000, 'Movie', str(tmp_path))
    target = tmp_path/'theme.mp3'
    if existing:
        target.write_bytes(b'external audio')
    config = Config(database_path=str(tmp_path/'worker.db'), staging_path=str(tmp_path/'staging'),
                    replacement_backup_path=str(tmp_path/'backups'), allowed_path=str(tmp_path))
    db = StateDB(config.database_path); db.initialize(); db.record_item(item, status)
    studio = Studio(config, db)
    identity = 'a'*32
    directory = studio.asset(identity); directory.mkdir()
    prepared = directory/'prepared.mp3'; prepared.write_bytes(b'new audio')
    (directory/'meta.json').write_text(json.dumps({'item_id': item.id, 'expected_sha256': sha256(target) if existing else None}))
    audio = AudioProcessor(45, '192k', 30, {})
    audio.validate = lambda path, **kw: {'duration': 45, 'sha256': sha256(path)}
    worker = SimpleNamespace(audio=audio, emby=SimpleNamespace(get_item=lambda _: item, refresh_and_verify=lambda *a, **kw: True))
    if existing:
        with pytest.raises(PermissionError, match='explicit takeover'):
            studio.execute(worker, 'apply', item.id, {'asset_id': identity})
        assert target.read_bytes() == b'external audio'
    result = studio.execute(worker, 'apply', item.id, {'asset_id': identity, 'adopt': existing})
    assert result['registered'] and result['locked']
    assert target.read_bytes() == b'new audio'
    with db.connect() as conn:
        replacement = conn.execute('SELECT * FROM replacements').fetchone()
    assert replacement['old_provider'] == 'external'
    assert db.item_state(item.id)['source_provider'] == 'manual'


@pytest.mark.parametrize('states,modes,sleeps', [([False, True], ['Default'], 1), ([False, False, True], ['Default', 'FullRefresh'], 2), ([False]*4, ['Default', 'FullRefresh'], 4)])
def test_refresh_waits_for_matching_bytes(monkeypatch, states, modes, sleeps):
    posts, waits = [], []
    def respond(request):
        posts.append(request.url.params['MetadataRefreshMode'])
        return httpx.Response(204)
    client = object.__new__(EmbyClient)
    client.client = httpx.Client(base_url='http://emby', transport=httpx.MockTransport(respond))
    results = iter(states)
    client.verify_theme_resource = lambda *args: next(results)
    monkeypatch.setattr('emby_theme_worker.emby.time.sleep', waits.append)
    try:
        assert client.refresh_and_verify('1', attempts=2, delay=.25, expected_path='/media/theme.mp3', expected_sha256='new') == any(states)
    finally:
        client.close()
    assert posts == modes and waits == [.25]*sleeps


@pytest.mark.parametrize('post_error', [False, True])
def test_refresh_paces_http_failures(monkeypatch, post_error):
    waits = []
    def respond(request):
        if post_error:
            raise httpx.ReadTimeout('offline')
        return httpx.Response(204)
    client = object.__new__(EmbyClient)
    client.client = httpx.Client(base_url='http://emby', transport=httpx.MockTransport(respond))
    def verify(*args):
        raise httpx.ReadTimeout('offline')
    client.verify_theme_resource = verify
    monkeypatch.setattr('emby_theme_worker.emby.time.sleep', waits.append)
    try:
        assert not client.refresh_and_verify('1', attempts=3, delay=.25, expected_path='/media/theme.mp3', expected_sha256='new')
    finally:
        client.close()
    assert waits == [.25]*(2 if post_error else 6)


class Chunks(httpx.SyncByteStream):
    def __init__(self, size): self.size = size
    def __iter__(self):
        left = self.size
        while left:
            chunk = b'a'*min(left, 256*1024)
            yield chunk
            left -= len(chunk)


def test_emby_readback_accepts_large_supported_track():
    size = 33*1024*1024
    digest = hashlib.sha256()
    for chunk in Chunks(size): digest.update(chunk)
    def respond(request):
        if request.url.path.endswith('ThemeSongs'):
            return httpx.Response(200, json={'Items': [{'Id': 'theme'}]})
        if request.url.path == '/Items':
            return httpx.Response(200, json={'Items': [{'Path': '/media/theme.mp3'}]})
        return httpx.Response(200, stream=Chunks(size))
    client = object.__new__(EmbyClient)
    client.client = httpx.Client(base_url='http://emby', transport=httpx.MockTransport(respond))
    try:
        assert client.verify_theme_resource('1', '/media/theme.mp3', digest.hexdigest())
        size = MAX_AUDIO_BYTES+1
        assert not client.verify_theme_resource('1', '/media/theme.mp3', digest.hexdigest())
    finally:
        client.close()


def test_audio_validation_rejects_over_budget_before_probe(tmp_path, monkeypatch):
    source = tmp_path/'large.mp3'
    with source.open('wb') as f: f.truncate(MAX_AUDIO_BYTES+1)
    monkeypatch.setattr('emby_theme_worker.audio.subprocess.run', lambda *a, **kw: pytest.fail('oversize audio must not be processed'))
    with pytest.raises(AudioSizeLimitError):
        AudioProcessor(45, '192k', 30, {}).validate_full(source)


def test_full_track_size_guard_never_truncates(tmp_path, monkeypatch):
    audio = AudioProcessor(45, '192k', 30, {})
    source, target = tmp_path/'source', tmp_path/'target.mp3'
    audio.validate_full = lambda *a, **kw: {'duration': MAX_AUDIO_BYTES*8/192000+1}
    monkeypatch.setattr('emby_theme_worker.audio.subprocess.run', lambda *a, **kw: pytest.fail('track should be rejected before transcoding'))
    with pytest.raises(AudioSizeLimitError, match='complete track'):
        audio._transcode(source, target, start=0, duration=None, strip_initial_silence=False)
    assert not target.exists()


def test_transcode_output_guard_rejects_and_removes_oversize(tmp_path, monkeypatch):
    audio = AudioProcessor(45, '192k', 30, {})
    target = tmp_path/'target.mp3'
    def run(command, **kw):
        assert '-fs' in command
        with target.open('wb') as f: f.truncate(MAX_AUDIO_BYTES+1)
    monkeypatch.setattr('emby_theme_worker.audio.subprocess.run', run)
    with pytest.raises(AudioSizeLimitError):
        audio._transcode(tmp_path/'source', target, start=0, duration=45, strip_initial_silence=False)
    assert not target.exists()


def test_studio_streams_large_supported_preview(tmp_path, monkeypatch):
    config = Config(database_path=str(tmp_path/'worker.db'), staging_path=str(tmp_path/'staging'), control_socket=str(tmp_path/'control.sock'))
    db = StateDB(config.database_path); db.initialize()
    studio = Studio(config, db)
    identity = 'a'*32
    directory = studio.asset(identity); directory.mkdir()
    source = directory/'prepared.mp3'
    size = 33*1024*1024
    with source.open('wb') as f: f.truncate(size)
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('preview must stream'))
    # Exercise the HTTP handler in process; no socket/network is needed.
    handlers = []
    def init_server(self, address, handler):
        Path(address).touch()
        handlers.append(handler)
    monkeypatch.setattr('emby_theme_worker.studio.socketserver.UnixStreamServer.__init__', init_server)
    monkeypatch.setattr('emby_theme_worker.studio.threading.Thread.start', lambda self: None)
    studio.start_server()
    try:
        handler = object.__new__(handlers[0])
        statuses, headers, lengths = [], {}, []
        handler.path = '/audio/'+identity
        handler.send_response = statuses.append
        handler.send_header = lambda k, v: headers.update({k: v})
        handler.end_headers = lambda: None
        handler.wfile = SimpleNamespace(write=lambda chunk: lengths.append(len(chunk)))
        handler.do_GET()
        assert statuses == [200]
        assert int(headers['Content-Length']) == size
        assert sum(lengths) == size and max(lengths) <= 256*1024
        with source.open('wb') as f: f.truncate(MAX_AUDIO_BYTES+1)
        handler.do_GET()
        assert statuses[-1] == 404
    finally:
        studio.server_lock.close()


def test_atomic_publish_rejects_oversize_before_writing(tmp_path):
    prepared = tmp_path/'large.mp3'
    with prepared.open('wb') as f: f.truncate(MAX_AUDIO_BYTES+1)
    media = tmp_path/'media'; media.mkdir()
    audio = AudioProcessor(45, '192k', 30, {})
    with pytest.raises(AudioSizeLimitError):
        audio.atomic_commit(prepared, media)
    target = media/'theme.mp3'
    assert not target.exists()
    target.write_bytes(b'old')
    with pytest.raises(AudioSizeLimitError):
        audio.atomic_replace_owned(prepared, target, sha256(target), tmp_path/'backup.mp3')
    assert target.read_bytes() == b'old'


def test_ytdlp_download_receives_shared_byte_budget(tmp_path, monkeypatch):
    from emby_theme_worker import ytdlp_runner
    calls = []
    monkeypatch.setattr(ytdlp_runner, '_run', lambda command, timeout: calls.append(command))
    ytdlp_runner.download('https://example.test/media', output_template=tmp_path/'source.%(ext)s', cookie_file=None,
                          socket_timeout_seconds=10, hard_timeout_seconds=60)
    command = calls[0]
    assert command[command.index('--max-filesize')+1] == str(MAX_AUDIO_BYTES)


def test_direct_download_enforces_shared_byte_budget(tmp_path, monkeypatch):
    from contextlib import contextmanager
    @contextmanager
    def stream(*args, **kwargs):
        yield httpx.Response(200, stream=Chunks(MAX_AUDIO_BYTES+1), request=httpx.Request('GET', 'https://example.test/media'))
    monkeypatch.setattr('emby_theme_worker.audio.httpx.stream', stream)
    with pytest.raises(AudioSizeLimitError):
        AudioProcessor(45, '192k', 30, {})._direct('https://example.test/media', tmp_path)


def test_validate_accepts_complete_track_above_old_budget(tmp_path, monkeypatch):
    source = tmp_path/'track.mp3'
    size = 33*1024*1024
    with source.open('wb') as f: f.truncate(size)
    metadata = {'format': {'duration': 1400, 'size': size}, 'streams': [{'codec_type': 'audio'}]}
    monkeypatch.setattr('emby_theme_worker.audio.subprocess.run', lambda *a, **kw: SimpleNamespace(stdout=json.dumps(metadata)))
    result = AudioProcessor(45, '192k', 30, {}).validate_full(source, expected_duration=1400)
    assert result['size'] == size and result['duration'] == 1400


@pytest.mark.parametrize('category,expected,hours', [('transient', 'network', 6), ('rate_limit', 'rate_limit', 6), (None, 'not_found', 720)])
def test_search_failure_uses_short_backoff(tmp_path, category, expected, hours):
    from datetime import datetime, UTC
    from emby_theme_worker.search_pipeline import SearchFailure, SearchResult
    from emby_theme_worker.worker import Worker
    config = Config(database_path=str(tmp_path/'worker.db'), allowed_path=str(tmp_path))
    db = StateDB(config.database_path); db.initialize()
    item = MediaItem('1', 'Movie', None, 2000, 'Movie', str(tmp_path))
    worker = object.__new__(Worker)
    worker.config, worker.db = config, db
    worker.emby = SimpleNamespace(theme_visible=lambda _: False)
    worker._search_results = SearchResult(failures=[SearchFailure('youtube', category, 'request_failed')] if category else [])
    worker._search = lambda _: worker._search_results
    def no_local(_): raise ValueError('no local media')
    worker._from_local = no_local
    result = worker.process(item)
    assert result['error_class'] == expected
    state = db.item_state(item.id)
    wait = (datetime.fromisoformat(state['retry_after']) - datetime.now(UTC)).total_seconds()/3600
    assert hours-.01 < wait <= hours


def test_search_partial_failure_does_not_discard_success(tmp_path):
    from emby_theme_worker.search_pipeline import SearchFailure, SearchResult
    from emby_theme_worker.models import Candidate
    from emby_theme_worker.worker import Worker
    config = Config(database_path=str(tmp_path/'worker.db'), allowed_path=str(tmp_path))
    db = StateDB(config.database_path); db.initialize()
    worker = object.__new__(Worker)
    worker.config, worker.db = config, db
    worker.emby = SimpleNamespace(theme_visible=lambda _: False)
    worker._search_results = SearchResult([Candidate('themerrdb', 'Movie', 'https://example.test/theme', exact=True)],
                                         [SearchFailure('youtube', 'rate_limit', 'blocked')])
    worker._search = lambda _: worker._search_results
    worker._from_candidate = lambda *a: {'status': 'complete'}
    assert worker.process(MediaItem('1', 'Movie', None, 2000, 'Movie', str(tmp_path)))['status'] == 'complete'



def test_download_rate_limit_uses_short_backoff(tmp_path):
    from emby_theme_worker.models import Candidate
    from emby_theme_worker.worker import Worker
    from emby_theme_worker.ytdlp_runner import YtDlpRateLimitError
    config = Config(database_path=str(tmp_path/'worker.db'), allowed_path=str(tmp_path))
    db = StateDB(config.database_path); db.initialize()
    worker = object.__new__(Worker)
    worker.config, worker.db = config, db
    worker.emby = SimpleNamespace(theme_visible=lambda _: False)
    worker._search = lambda _: [Candidate('themerrdb', 'Movie theme', 'https://example.test/theme', exact=True)]
    def limited(*a): raise YtDlpRateLimitError('transport_rate_limited')
    def no_local(*a): raise ValueError('no local audio')
    worker._from_candidate, worker._from_local = limited, no_local
    result = worker.process(MediaItem('1', 'Movie', None, 2000, 'Movie', str(tmp_path)))
    assert result['error_class'] == 'rate_limit'
