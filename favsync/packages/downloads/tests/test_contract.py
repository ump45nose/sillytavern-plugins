from __future__ import annotations

import subprocess
import sys
import time

import pytest

from favsync_downloads import DownloadError, DownloadTimeout, download_http
from favsync_downloads import transports


@pytest.mark.parametrize("parameter,value", [
    ("timeout_seconds", 0), ("timeout_seconds", -1), ("timeout_seconds", True),
    ("hard_timeout_seconds", float("inf")), ("hard_timeout_seconds", float("nan")),
    ("max_bytes", 0), ("max_bytes", 3.5), ("max_bytes", "100"),
])
def test_invalid_budgets(tmp_path, parameter, value):
    kwargs = dict(timeout_seconds=1, hard_timeout_seconds=1, max_bytes=10)
    kwargs[parameter] = value
    with pytest.raises(DownloadError, match="invalid_"):
        download_http("https://example.invalid/PRIVATE", workdir=tmp_path, **kwargs)
    assert not list(tmp_path.iterdir())


def test_symlink_workdir_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(DownloadError, match="unsafe_workdir"):
        download_http("https://example.invalid", workdir=link, timeout_seconds=1, hard_timeout_seconds=1, max_bytes=10)
    assert not list(real.iterdir())


def test_symlink_parent_rejected(tmp_path):
    real = tmp_path / "real"
    (real / "nested").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(DownloadError, match="unsafe_workdir"):
        download_http("https://example.invalid", workdir=link / "nested", timeout_seconds=1, hard_timeout_seconds=1, max_bytes=10)


def test_deadline_covers_final_validation(monkeypatch, tmp_path):
    with pytest.raises(DownloadTimeout):
        with transports._workspace(tmp_path, 1, 0.01, 10) as (stage, deadline):
            (stage / "download").write_bytes(b"x")
            time.sleep(0.02)
    assert not list(tmp_path.iterdir())


def test_cancellation_cleans_owned_stage_only(tmp_path):
    unrelated = tmp_path / "keep"
    unrelated.write_text("untouched")
    with pytest.raises(KeyboardInterrupt):
        with transports._workspace(tmp_path, 1, 1, 10) as (stage, deadline):
            (stage / "download.part").write_bytes(b"x")
            raise KeyboardInterrupt
    assert list(tmp_path.iterdir()) == [unrelated]


def test_import_has_no_side_effects():
    code = '''
import builtins, os, pathlib, socket, subprocess, tempfile

def forbidden(*args, **kwargs):
    raise AssertionError("import performed I/O")
builtins.open = forbidden
pathlib.Path.open = forbidden
socket.socket = forbidden
subprocess.Popen = forbidden
tempfile.mkdtemp = forbidden
import favsync_downloads
assert "favsync" not in __import__("sys").modules
assert "emby_theme_worker" not in __import__("sys").modules
assert "httpx" not in __import__("sys").modules
assert "yt_dlp" not in __import__("sys").modules
'''
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
