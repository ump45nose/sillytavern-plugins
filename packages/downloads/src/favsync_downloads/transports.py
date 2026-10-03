from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

from .errors import (
    DownloadError,
    DownloadRateLimitError,
    DownloadServiceError,
    DownloadSizeLimitError,
    DownloadTimeout,
    classify_ytdlp_error,
)

_POLL_SECONDS = 0.05
_MAX_STDERR_BYTES = 64 * 1024
_MAX_COOKIE_BYTES = 4 * 1024 * 1024
_HTTP_ERRORS = {
    "transport_rate_limited": DownloadRateLimitError,
    "transport_blocked_or_unavailable": DownloadServiceError,
    "download_size_limit_exceeded": DownloadSizeLimitError,
    "socket_timeout": DownloadTimeout,
    "item_unavailable": DownloadError,
    "empty_download": DownloadError,
}


def _positive(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise DownloadError(f"invalid_{name}")


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise DownloadTimeout("download_deadline_exceeded")


@contextmanager
def _workspace(workdir: Path, timeout: int, hard_timeout: int, max_bytes: int) -> Iterator[tuple[Path, float]]:
    _positive(timeout, "socket_timeout")
    _positive(hard_timeout, "hard_timeout")
    _positive(max_bytes, "max_bytes")
    if not isinstance(max_bytes, int):
        raise DownloadError("invalid_max_bytes")
    deadline = time.monotonic() + hard_timeout
    stage: Path | None = None
    try:
        root = Path(workdir).absolute()
        # The caller owns this existing directory. No symlink component is accepted.
        if root.resolve(strict=True) != root or not root.is_dir():
            raise DownloadError("unsafe_workdir")
        stage = Path(tempfile.mkdtemp(prefix=".favsync-download-", dir=root))
        yield stage, deadline
        _check_deadline(deadline)
    except BaseException as exc:
        if stage is not None:
            shutil.rmtree(stage, ignore_errors=True)
        if isinstance(exc, OSError):
            raise DownloadError("filesystem_unavailable") from None
        raise


def _files(stage: Path, max_bytes: int) -> list[Path]:
    """Inspect without following links; also bound in-flight aggregate disk output."""
    if stage.is_symlink() or not stage.is_dir():
        raise DownloadError("unsafe_artifact")
    files: list[Path] = []
    total = 0
    count = 0
    pending = [stage]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > 256:
                    raise DownloadError("artifact_count_limit_exceeded")
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:  # yt-dlp can atomically rename a part file.
                    continue
                if stat.S_ISLNK(info.st_mode):
                    raise DownloadError("unsafe_artifact")
                path = Path(entry.path)
                if not path.resolve().is_relative_to(stage):
                    raise DownloadError("unsafe_artifact")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_size
                    if total > max_bytes:
                        raise DownloadSizeLimitError("download_size_limit_exceeded")
                    files.append(path)
                else:
                    raise DownloadError("unsafe_artifact")
    return files


def _artifact(stage: Path, max_bytes: int, pattern: str) -> Path:
    files = _files(stage, max_bytes)
    if len(files) != 1:
        raise DownloadError("missing_or_ambiguous_artifact")
    target = files[0]
    if (target.parent != stage or re.fullmatch(pattern, target.name) is None
            or target.suffix.lower() in {".part", ".ytdl", ".temp", ".tmp", ".partial"}
            or len(list(stage.iterdir())) != 1):
        raise DownloadError("incomplete_or_unexpected_artifact")
    if target.stat().st_size == 0:
        raise DownloadError("empty_download")
    return target


def _kill_group(process: subprocess.Popen) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait()


def _run(command: list[str], *, stage: Path, deadline: float, max_bytes: int, request: bytes | None = None) -> tuple[int, str]:
    _check_deadline(deadline)
    # stderr is bounded and never exposed. stdout carries no required protocol data.
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE if request is not None else subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=stderr, start_new_session=True,
        )
        try:
            first = True
            while True:
                _check_deadline(deadline)
                _files(stage, max_bytes)
                if os.fstat(stderr.fileno()).st_size > _MAX_STDERR_BYTES:
                    raise DownloadError("download_log_limit_exceeded")
                remaining = deadline - time.monotonic()
                try:
                    process.communicate(input=request if first else None, timeout=min(_POLL_SECONDS, max(remaining, 0.001)))
                    break
                except subprocess.TimeoutExpired:
                    first = False
            _check_deadline(deadline)
            _files(stage, max_bytes)
            if os.fstat(stderr.fileno()).st_size > _MAX_STDERR_BYTES:
                raise DownloadError("download_log_limit_exceeded")
            stderr.seek(0)
            return process.returncode, stderr.read(_MAX_STDERR_BYTES).decode("utf-8", errors="replace")
        finally:
            # Kill remaining descendants even if their process-group leader exited.
            _kill_group(process)
            if process.stdin:
                process.stdin.close()


@contextmanager
def _cookie_copy(cookie_file: str | None, deadline: float) -> Iterator[str | None]:
    if not cookie_file:
        yield None
        return
    source = Path(cookie_file)
    try:
        info = source.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > _MAX_COOKIE_BYTES:
            raise DownloadError("cookie_file_unavailable")
        with tempfile.TemporaryDirectory(prefix="favsync-cookie-") as directory:
            target = Path(directory) / "cookies.txt"
            # Restricted directory and explicit mode protect the writable copy.
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with source.open("rb") as src, os.fdopen(descriptor, "wb") as dst:
                copied = 0
                while chunk := src.read(64 * 1024):
                    _check_deadline(deadline)
                    copied += len(chunk)
                    if copied > _MAX_COOKIE_BYTES:
                        raise DownloadError("cookie_file_unavailable")
                    dst.write(chunk)
            yield str(target)
    except OSError:
        raise DownloadError("cookie_file_unavailable") from None


def download_http(url: str, *, workdir: Path, timeout_seconds: int, hard_timeout_seconds: int, max_bytes: int) -> Path:
    """Download one HTTP(S) artifact with socket, wall-clock and decoded-byte limits."""
    if not isinstance(url, str) or "\x00" in url:
        raise DownloadError("invalid_http_url")
    try:
        parsed = urlsplit(url)
        valid = isinstance(url, str) and parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise DownloadError("invalid_http_url")
    suffix = Path(parsed.path).suffix
    if re.fullmatch(r"\.[A-Za-z0-9]{1,9}", suffix) is None:
        suffix = ".media"
    with _workspace(workdir, timeout_seconds, hard_timeout_seconds, max_bytes) as (stage, deadline):
        target = stage / f"download{suffix}"
        code, message = _run(
            [sys.executable, "-m", "favsync_downloads._http_worker"],
            stage=stage, deadline=deadline, max_bytes=max_bytes,
            request=json.dumps({"url": url, "target": str(target), "timeout_seconds": timeout_seconds, "max_bytes": max_bytes}).encode(),
        )
        if code:
            error_type = _HTTP_ERRORS.get(message, DownloadError)
            raise error_type(message if message in _HTTP_ERRORS else "download_failed")
        return _artifact(stage, max_bytes, re.escape(target.name))


def download_ytdlp(source: str, *, workdir: Path, cookie_file: str | None, socket_timeout_seconds: int, hard_timeout_seconds: int, max_bytes: int) -> Path:
    """Download one best-audio artifact; only explicitly supplied cookies are read."""
    if not isinstance(source, str) or not source.strip() or "\x00" in source:
        raise DownloadError("invalid_source")
    if importlib.util.find_spec("yt_dlp") is None:
        raise DownloadServiceError("ytdlp_not_installed")
    with _workspace(workdir, socket_timeout_seconds, hard_timeout_seconds, max_bytes) as (stage, deadline):
        with _cookie_copy(cookie_file, deadline) as cookie:
            command = [
                sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-cache-dir",
                "--quiet", "--no-warnings", "--no-progress", "--js-runtimes", "deno",
                "--socket-timeout", str(min(socket_timeout_seconds, 15)),
                "--retries", "1", "--fragment-retries", "1", "--extractor-retries", "1",
                "--file-access-retries", "1", "--no-playlist", "--no-simulate",
                "--max-filesize", str(max_bytes), "--format", "bestaudio/best",
                "--output", str(stage / "source.%(ext)s"),
            ]
            if cookie:
                command.extend(["--cookies", cookie])
            command.extend(["--", source])
            code, message = _run(command, stage=stage, deadline=deadline, max_bytes=max_bytes)
            if code:
                raise classify_ytdlp_error(message)
        return _artifact(stage, max_bytes, r"source\.[A-Za-z0-9]{1,16}")
