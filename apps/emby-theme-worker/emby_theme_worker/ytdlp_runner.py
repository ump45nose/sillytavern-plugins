from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .media_limits import MAX_AUDIO_BYTES


class YtDlpError(RuntimeError):
    """A redacted yt-dlp failure."""


class YtDlpTimeout(YtDlpError):
    """yt-dlp exceeded its wall-clock deadline."""


class YtDlpServiceError(YtDlpError):
    """A blocked or unavailable transport, without upstream secret text."""


class YtDlpRateLimitError(YtDlpServiceError):
    """An explicit rate limit, preserved without the upstream message."""


def classify_error(stderr: str) -> YtDlpError:
    text = stderr.casefold()
    # Item-level failures must not disable the entire service.
    if any(word in text for word in ("video unavailable", "private video", "removed", "not available in your country", "copyright", "requested format is not available")):
        return YtDlpError("item_unavailable")
    if "429" in text:
        return YtDlpRateLimitError("transport_rate_limited")
    if any(word in text for word in ("sign in", "confirm you", "403", "429", "timed out", "connection", "network", "502", "503", "unable to download webpage")):
        return YtDlpServiceError("transport_blocked_or_unavailable")
    return YtDlpError("unclassified_download_failure")


@contextmanager
def _writable_cookie(cookie_file: str | None) -> Iterator[str | None]:
    if not cookie_file or not Path(cookie_file).is_file():
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="yt-dlp-cookie-") as directory:
        target = Path(directory) / "cookies.txt"
        shutil.copyfile(cookie_file, target)
        target.chmod(0o600)
        yield str(target)


def _run(command: list[str], timeout_seconds: int) -> str:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise YtDlpTimeout(f"yt-dlp exceeded {timeout_seconds}s deadline") from exc
    if process.returncode:
        raise classify_error(_stderr)
    return stdout


def _base(socket_timeout_seconds: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-cache-dir",
        "--quiet",
        "--no-warnings",
        "--no-progress",
        "--js-runtimes",
        "deno",
        "--socket-timeout",
        str(min(socket_timeout_seconds, 15)),
        "--retries",
        "1",
        "--fragment-retries",
        "1",
        "--extractor-retries",
        "1",
        "--file-access-retries",
        "1",
    ]


def search(
    query: str,
    *,
    cookie_file: str | None,
    socket_timeout_seconds: int,
    hard_timeout_seconds: int,
) -> dict:
    with _writable_cookie(cookie_file) as cookie:
        command = _base(socket_timeout_seconds)
        command.extend(["--flat-playlist", "--playlist-end", "10", "--dump-single-json"])
        if cookie:
            command.extend(["--cookies", cookie])
        command.extend(["--", query])
        output = _run(command, hard_timeout_seconds)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise YtDlpError("yt-dlp returned invalid JSON") from exc


def download(
    source: str,
    *,
    output_template: Path,
    cookie_file: str | None,
    socket_timeout_seconds: int,
    hard_timeout_seconds: int,
) -> None:
    with _writable_cookie(cookie_file) as cookie:
        command = _base(socket_timeout_seconds)
        command.extend([
            "--no-playlist",
            "--no-simulate",
            "--max-filesize",
            str(MAX_AUDIO_BYTES),
            "--format",
            "bestaudio/best",
            "--output",
            str(output_template),
        ])
        if cookie:
            command.extend(["--cookies", cookie])
        command.extend(["--", source])
        _run(command, hard_timeout_seconds)
