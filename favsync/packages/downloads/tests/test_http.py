from __future__ import annotations

import time

import pytest

from favsync_downloads import (
    DownloadError, DownloadRateLimitError, DownloadServiceError,
    DownloadSizeLimitError, DownloadTimeout, download_http,
)


def fetch(url, workdir, **kwargs):
    options = dict(timeout_seconds=3, hard_timeout_seconds=4, max_bytes=1000)
    options.update(kwargs)
    return download_http(url, workdir=workdir, **options)


@pytest.mark.parametrize("route,suffix", [("/ok.mp3", ".mp3"), ("/no-length", ".media"), ("/redirect", ".media"), ("/strange.abcdefghijkl", ".media")])
def test_success(http_server, tmp_path, route, suffix):
    target = fetch(http_server + route, tmp_path)
    assert target.read_bytes() == b"test-media-data"
    assert target.suffix == suffix
    assert target.resolve().is_relative_to(tmp_path)
    assert target.parent != tmp_path
    assert list(target.parent.iterdir()) == [target]


def test_existing_files_not_selected_or_overwritten(http_server, tmp_path):
    existing = tmp_path / "download.mp3"
    existing.write_bytes(b"existing")
    first = fetch(http_server + "/ok.mp3", tmp_path)
    second = fetch(http_server + "/ok.mp3", tmp_path)
    assert first != second
    assert first.read_bytes() == second.read_bytes()
    assert existing.read_bytes() == b"existing"


@pytest.mark.parametrize("route", ["/ok.mp3", "/no-length", "/large-header", "/gzip"])
def test_size_limits_use_actual_bytes_and_header(http_server, tmp_path, route):
    max_bytes = 100 if route == "/gzip" else 4
    with pytest.raises(DownloadSizeLimitError, match="download_size_limit_exceeded"):
        fetch(http_server + route, tmp_path, max_bytes=max_bytes)
    assert not list(tmp_path.iterdir())


def test_exact_size_limit_passes(http_server, tmp_path):
    target = fetch(http_server + "/ok.mp3", tmp_path, max_bytes=len(b"test-media-data"))
    assert target.read_bytes() == b"test-media-data"


@pytest.mark.parametrize("route", ["/stall-headers", "/stall-body", "/trickle"])
def test_absolute_deadline_includes_stalled_reads(http_server, tmp_path, route):
    start = time.monotonic()
    with pytest.raises(DownloadTimeout, match="download_deadline_exceeded"):
        fetch(http_server + route, tmp_path, hard_timeout_seconds=0.45, max_bytes=200000)
    assert time.monotonic() - start < 1.5
    assert not list(tmp_path.iterdir())


def test_socket_timeout(http_server, tmp_path):
    with pytest.raises(DownloadTimeout, match="socket_timeout"):
        fetch(http_server + "/stall-headers", tmp_path, timeout_seconds=0.15)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("status,error", [(401, DownloadServiceError), (403, DownloadServiceError), (429, DownloadRateLimitError), (503, DownloadServiceError), (404, DownloadError)])
def test_http_status_is_redacted(http_server, tmp_path, status, error):
    with pytest.raises(error) as caught:
        fetch(http_server + f"/status/{status}?token=PRIVATE", tmp_path)
    assert "PRIVATE" not in str(caught.value)
    assert http_server not in str(caught.value)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("route", ["/empty", "/truncated"])
def test_invalid_body_rejected_and_cleaned(http_server, tmp_path, route):
    with pytest.raises(DownloadError):
        fetch(http_server + route, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/path", "http://", "https://[broken", None, 42, "http://host/\x00PRIVATE"])
def test_invalid_url_is_redacted(tmp_path, url):
    with pytest.raises(DownloadError, match="invalid_http_url"):
        fetch(url, tmp_path)
    assert not list(tmp_path.iterdir())
