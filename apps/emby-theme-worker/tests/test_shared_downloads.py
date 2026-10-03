"""Optional-package contract; both installed and standalone paths stay usable."""
import builtins
import sys
from types import SimpleNamespace

import pytest

from emby_theme_worker.audio import AudioProcessor
from emby_theme_worker.media_limits import AudioSizeLimitError, MAX_AUDIO_BYTES
from emby_theme_worker.models import Candidate
from emby_theme_worker.ytdlp_runner import YtDlpError, YtDlpRateLimitError, YtDlpServiceError, YtDlpTimeout


@pytest.fixture
def shared(monkeypatch):
    class DownloadError(Exception): pass
    class DownloadServiceError(DownloadError): pass
    class DownloadRateLimitError(DownloadServiceError): pass
    class DownloadTimeout(DownloadError): pass
    class DownloadSizeLimitError(DownloadError): pass
    module = SimpleNamespace(**locals())
    monkeypatch.setitem(sys.modules, 'favsync_downloads', module)
    return module


@pytest.mark.parametrize('transport', ['direct_http', 'youtube'])
def test_installed_package_gets_only_transport_arguments(tmp_path, shared, transport):
    result = tmp_path/'private'/'artifact.mp3'
    calls = []
    def download(source, **kwargs):
        calls.append((source, kwargs))
        return result
    shared.download_http = shared.download_ytdlp = download
    audio = AudioProcessor(45, '192k', 17, {'youtube': '/run/secrets/youtube'}, 61)
    audio._direct = audio._ytdlp = lambda *a: pytest.fail('installed package must be used')
    candidate = Candidate('themerrdb', 'Theme', 'https://example.test/media', transport=transport)
    assert audio.fetch_candidate(candidate, tmp_path) == result
    source, options = calls[0]
    assert source == candidate.source_url
    assert options['workdir'] == tmp_path
    assert options['max_bytes'] == MAX_AUDIO_BYTES and options['hard_timeout_seconds'] == 61
    if transport == 'youtube':
        assert options == {'workdir': tmp_path, 'cookie_file': '/run/secrets/youtube', 'socket_timeout_seconds': 17,
                           'hard_timeout_seconds': 61, 'max_bytes': MAX_AUDIO_BYTES}
    else:
        assert options == {'workdir': tmp_path, 'timeout_seconds': 17, 'hard_timeout_seconds': 61, 'max_bytes': MAX_AUDIO_BYTES}


@pytest.mark.parametrize('transport', ['direct_http', 'youtube'])
def test_absent_package_preserves_standalone_transport(tmp_path, monkeypatch, transport):
    original_import = builtins.__import__
    def import_module(name, *args, **kwargs):
        if name == 'favsync_downloads':
            raise ModuleNotFoundError('optional package absent', name='favsync_downloads')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', import_module)
    audio = AudioProcessor(45, '192k', 30, {})
    calls = []
    audio._direct = lambda *args: calls.append(('http', args)) or tmp_path/'http.mp3'
    audio._ytdlp = lambda *args: calls.append(('ytdlp', args)) or tmp_path/'yt.mp3'
    candidate = Candidate('resolver', 'Theme', 'https://example.test/media', transport=transport)
    assert audio.fetch_candidate(candidate, tmp_path) == tmp_path/('yt.mp3' if transport == 'youtube' else 'http.mp3')
    assert calls[0][0] == ('ytdlp' if transport == 'youtube' else 'http')


@pytest.mark.parametrize('error_name,expected', [('DownloadError', YtDlpError), ('DownloadServiceError', YtDlpServiceError),
    ('DownloadRateLimitError', YtDlpRateLimitError), ('DownloadTimeout', YtDlpTimeout), ('DownloadSizeLimitError', AudioSizeLimitError)])
def test_shared_errors_keep_theme_health_and_backoff_contract(tmp_path, shared, error_name, expected):
    def fail(*a, **kw): raise getattr(shared, error_name)('redacted')
    shared.download_http = fail
    with pytest.raises(expected) as exc:
        AudioProcessor(45, '192k', 30, {}).fetch_candidate(Candidate('resolver', 'Theme', 'https://example.test/media'), tmp_path)
    assert type(exc.value) is expected


def test_broken_installed_package_does_not_silently_fallback(tmp_path, monkeypatch):
    original_import = builtins.__import__
    def import_module(name, *args, **kwargs):
        if name == 'favsync_downloads':
            raise ModuleNotFoundError('broken dependency', name='missing_dependency')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', import_module)
    audio = AudioProcessor(45, '192k', 30, {})
    audio._direct = lambda *a: pytest.fail('must not fallback from broken package')
    with pytest.raises(ModuleNotFoundError, match='broken dependency'):
        audio.fetch_candidate(Candidate('resolver', 'Theme', 'https://example.test/media'), tmp_path)
