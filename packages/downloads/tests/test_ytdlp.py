from __future__ import annotations

import json
import time

import pytest

from favsync_downloads import (
    DownloadError, DownloadRateLimitError, DownloadServiceError,
    DownloadSizeLimitError, DownloadTimeout, download_ytdlp,
)


def fetch(source, workdir, **kwargs):
    options = dict(cookie_file=None, socket_timeout_seconds=30, hard_timeout_seconds=4, max_bytes=1000)
    options.update(kwargs)
    return download_ytdlp(source, workdir=workdir, **options)


@pytest.fixture
def workdir(tmp_path):
    path = tmp_path / "downloads"
    path.mkdir()
    return path


def test_success_flags(stub_ytdlp, workdir):
    result = fetch("success", workdir)
    assert result.read_bytes() == b"media bytes"
    args = json.loads(stub_ytdlp["capture"].read_text())["args"]
    assert args[-2:] == ["--", "success"]
    for flag in ("--ignore-config", "--no-cache-dir", "--no-playlist", "--no-simulate"):
        assert flag in args
    assert args[args.index("--socket-timeout") + 1] == "15"
    assert args[args.index("--format") + 1] == "bestaudio/best"
    assert args[args.index("--max-filesize") + 1] == "1000"
    assert "--cookies" not in args


@pytest.mark.parametrize("mode", ["empty", "none", "multiple", "partial", "bare-partial", "nested", "symlink", "hardlink"])
def test_rejects_invalid_artifacts(stub_ytdlp, workdir, mode):
    with pytest.raises(DownloadError):
        fetch(mode, workdir)
    assert not list(workdir.iterdir())
    assert stub_ytdlp["outside"].read_bytes() == b"original outside bytes"


@pytest.mark.parametrize("mode", ["large", "aggregate-large", "growing"])
def test_actual_and_aggregate_size_limits(stub_ytdlp, workdir, mode):
    with pytest.raises(DownloadSizeLimitError):
        fetch(mode, workdir, max_bytes=100)
    assert not list(workdir.iterdir())


@pytest.mark.parametrize("mode", ["success", "error:403", "timeout"])
def test_cookie_copy_private_unchanged_and_removed(stub_ytdlp, workdir, tmp_path, mode):
    cookie = tmp_path / "my-secret-cookies.txt"
    cookie.write_text("# Netscape\nORIGINAL-cookie-secret")
    cookie.chmod(0o400)
    try:
        fetch(mode, workdir, cookie_file=str(cookie), hard_timeout_seconds=0.45)
    except DownloadError:
        assert mode != "success"
    info = json.loads(stub_ytdlp["capture"].read_text())
    assert info["cookie_mode"] == 0o600
    assert info["cookie_content"] == cookie.read_text()
    assert info["cookie"] != str(cookie)
    assert not __import__("pathlib").Path(info["cookie"]).exists()
    assert cookie.read_text() == "# Netscape\nORIGINAL-cookie-secret"
    assert cookie.stat().st_mode & 0o777 == 0o400


@pytest.mark.parametrize("cookie_kind", ["missing", "directory", "oversized"])
def test_invalid_cookie_fails_closed(stub_ytdlp, workdir, tmp_path, cookie_kind):
    cookie = tmp_path / "cookie"
    if cookie_kind == "directory":
        cookie.mkdir()
    elif cookie_kind == "oversized":
        cookie.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    with pytest.raises(DownloadError, match="cookie_file_unavailable"):
        fetch("success", workdir, cookie_file=str(cookie))
    assert not list(workdir.iterdir())
    assert not stub_ytdlp["capture"].exists()


@pytest.mark.parametrize("message,error,code", [
    ("Video unavailable 403", DownloadError, "item_unavailable"),
    ("429", DownloadRateLimitError, "transport_rate_limited"),
    ("403 sign in", DownloadServiceError, "transport_blocked_or_unavailable"),
    ("network error", DownloadServiceError, "transport_blocked_or_unavailable"),
    ("unexpected", DownloadError, "unclassified_download_failure"),
])
def test_error_classification_redacts_upstream(stub_ytdlp, workdir, message, error, code):
    with pytest.raises(error) as caught:
        fetch("error:" + message, workdir)
    assert str(caught.value) == code
    if code == "item_unavailable":
        assert not isinstance(caught.value, DownloadServiceError)
    assert not list(workdir.iterdir())


@pytest.mark.parametrize("mode", ["timeout", "leader-exit"])
def test_process_group_descendants_killed(stub_ytdlp, workdir, mode):
    start = time.monotonic()
    if mode == "timeout":
        with pytest.raises(DownloadTimeout):
            fetch(mode, workdir, hard_timeout_seconds=0.4)
        assert not list(workdir.iterdir())
    else:
        assert fetch(mode, workdir).read_bytes() == b"media"
    assert time.monotonic() - start < 1.2
    time.sleep(1.1)
    assert not stub_ytdlp["child_marker"].exists()


def test_log_resource_budget_and_redaction(stub_ytdlp, workdir):
    with pytest.raises(DownloadError, match="download_log_limit_exceeded"):
        fetch("log-flood", workdir)
    assert not list(workdir.iterdir())


def test_optional_dependency_absent(monkeypatch, workdir):
    monkeypatch.setattr("favsync_downloads.transports.importlib.util.find_spec", lambda name: None)
    with pytest.raises(DownloadServiceError, match="ytdlp_not_installed"):
        fetch("source", workdir)
    assert not list(workdir.iterdir())
