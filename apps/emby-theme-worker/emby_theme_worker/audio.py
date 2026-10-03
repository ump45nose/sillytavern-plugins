from __future__ import annotations

import fcntl
import hashlib
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from array import array
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from .models import Candidate
from .media_limits import AudioSizeLimitError, MAX_AUDIO_BYTES, STREAM_CHUNK_BYTES
from .security import safe_http_url_from_strm
from .ytdlp_runner import download as ytdlp_download


LOG = logging.getLogger(__name__)


class AudioProcessor:
    def __init__(
        self,
        target_seconds: int,
        bitrate: str,
        timeout: int,
        cookies: dict[str, str],
        ytdlp_download_timeout: int = 180,
    ):
        self.target_seconds = target_seconds
        self.bitrate = bitrate
        self.timeout = timeout
        self.cookies = cookies
        self.ytdlp_download_timeout = ytdlp_download_timeout

    def fetch_candidate(self, candidate: Candidate, workdir: Path) -> Path:
        source = candidate.source_url
        transport = candidate.transport or candidate.provider
        use_ytdlp = source.startswith(("ytsearch", "bilisearch")) or transport in {"youtube", "bilibili", "netease", "qqmusic"}
        try:
            import favsync_downloads as shared
        except ModuleNotFoundError as exc:
            if exc.name != 'favsync_downloads':
                raise  # A broken installed package is not an absent optional extra.
            shared = None
        if shared is not None:
            from .ytdlp_runner import YtDlpError, YtDlpTimeout, YtDlpServiceError, YtDlpRateLimitError
            try:
                if use_ytdlp:
                    return shared.download_ytdlp(
                        source, workdir=workdir, cookie_file=self.cookies.get(transport),
                        socket_timeout_seconds=self.timeout, hard_timeout_seconds=self.ytdlp_download_timeout,
                        max_bytes=MAX_AUDIO_BYTES)
                return shared.download_http(
                    source, workdir=workdir, timeout_seconds=self.timeout,
                    hard_timeout_seconds=self.ytdlp_download_timeout, max_bytes=MAX_AUDIO_BYTES)
            except shared.DownloadSizeLimitError as exc:
                raise AudioSizeLimitError('audio exceeds 64 MiB media budget') from exc
            except shared.DownloadRateLimitError as exc:
                raise YtDlpRateLimitError('transport_rate_limited') from exc
            except shared.DownloadTimeout as exc:
                raise YtDlpTimeout('shared download deadline exceeded') from exc
            except shared.DownloadServiceError as exc:
                raise YtDlpServiceError('transport_blocked_or_unavailable') from exc
            except shared.DownloadError as exc:
                raise YtDlpError('item_download_failed') from exc
        # Staging compatibility: default standalone installs keep their existing
        # transport until the independently built optional wheel is installed.
        if use_ytdlp:
            return self._ytdlp(source, transport, workdir)
        return self._direct(source, workdir)

    def _direct(self, url: str, workdir: Path) -> Path:
        suffix = Path(urlsplit(url).path).suffix or ".media"
        target = workdir / f"download{suffix[:10]}"
        started, total = time.monotonic(), 0
        with httpx.stream("GET", url, timeout=self.timeout, follow_redirects=True, headers={"User-Agent": "emby-theme-worker/0.1"}) as response:
            response.raise_for_status()
            with target.open("wb") as handle:
                for chunk in response.iter_bytes(STREAM_CHUNK_BYTES):
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise AudioSizeLimitError('audio exceeds 64 MiB media budget')
                    if time.monotonic()-started > self.ytdlp_download_timeout:
                        raise TimeoutError('direct download deadline exceeded')
                    handle.write(chunk)
        return target

    def _ytdlp(self, url: str, provider: str, workdir: Path) -> Path:
        template = str(workdir / "source.%(ext)s")
        cookie = self.cookies.get(provider)
        ytdlp_download(
            url,
            output_template=Path(template),
            cookie_file=cookie,
            socket_timeout_seconds=self.timeout,
            hard_timeout_seconds=self.ytdlp_download_timeout,
        )
        matches = list(workdir.glob("source.*"))
        if not matches:
            raise FileNotFoundError("yt-dlp produced no media")
        if matches[0].stat().st_size > MAX_AUDIO_BYTES:
            raise AudioSizeLimitError('audio exceeds 64 MiB media budget')
        return matches[0]

    def normalize_online(self, source: Path, target: Path) -> dict:
        self.validate_source(source)
        original = self.validate_full(source)
        # Online/manual music is a complete track unless a user explicitly trims it.
        self._transcode(source, target, start=0, duration=None, strip_initial_silence=False)
        self.validate_full(target, expected_duration=original['duration'])
        return {'mode': 'full', 'start': 0, 'duration': original['duration']}

    def validate_full(self, path: Path, *, expected_duration: float | None = None) -> dict:
        info = self.validate(path, min_duration=1, max_duration=float('inf'))
        if expected_duration is not None and abs(info['duration'] - expected_duration) > 1:
            raise ValueError('track duration changed during processing')
        return info

    def validate_source(self, source: Path) -> None:
        import json
        command=['ffprobe','-v','error','-protocol_whitelist','file,pipe','-show_entries','format=format_name','-of','json',str(source)]
        info=json.loads(subprocess.run(command,check=True,capture_output=True,text=True,timeout=30).stdout)
        formats=set(info.get('format',{}).get('format_name','').split(','))
        if not formats & {'mp3','wav','flac','ogg','mov','mp4','m4a','matroska','webm','aac','aiff','asf','mpeg','mpegts'}:
            raise ValueError('unsupported audio container or playlist')

    def smart_extract(self, media_path: str, target: Path, ranges: list[tuple[float, float]]) -> dict:
        from .segments import analyze
        source = media_path
        if media_path.casefold().endswith(".strm"):
            source = safe_http_url_from_strm(Path(media_path).read_text(encoding="utf-8-sig"))
        choices = [analyze(source, start, duration) for start, duration in ranges if duration > 0]
        if not choices:
            raise ValueError("no extractable interval")
        best = max(choices, key=lambda c: (c["quality"] == "high", c.get("shares", {}).get("music", 0), -c.get("penalty", 1)))
        self._transcode(source, target, start=best["start"], duration=best["duration"], strip_initial_silence=False)
        return best

    def extract_opening(self, media_path: str, target: Path) -> None:
        source = media_path
        if media_path.casefold().endswith(".strm"):
            source = safe_http_url_from_strm(Path(media_path).read_text(encoding="utf-8-sig"))
        self._transcode(source, target, start=0, duration=self.target_seconds, strip_initial_silence=True)

    def extract_intro(self, media_path: str, target: Path, start: float, end: float) -> float:
        duration = end - start
        if duration < 30:
            raise ValueError("intro marker span is shorter than 30 seconds")
        source = media_path
        if media_path.casefold().endswith(".strm"):
            source = safe_http_url_from_strm(Path(media_path).read_text(encoding="utf-8-sig"))
        output_duration = min(duration, 60.0)
        selected_start = start
        if duration > 60:
            from .segments import analyze
            selected_start = analyze(source, start, duration)["start"]
            output_duration = float(self.target_seconds)
        self._transcode(source, target, start=selected_start, duration=output_duration, strip_initial_silence=False)
        return output_duration

    def _highest_energy_start(self, source: str | Path, *, range_start: float = 0, max_duration: float = 1200) -> float:
        command = ["ffmpeg", "-v", "error"]
        if range_start:
            command.extend(["-ss", f"{range_start:.3f}"])
        command.extend([
            "-i", str(source), "-t", f"{min(max_duration, 1200):.3f}", "-vn",
            "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
        ])
        raw = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300).stdout
        samples = array("h")
        samples.frombytes(raw)
        per_second = 8000
        rms: list[float] = []
        for offset in range(0, len(samples), per_second):
            window = samples[offset:offset + per_second]
            if not window:
                continue
            rms.append(sum(value * value for value in window) / len(window))
        width = min(self.target_seconds, len(rms))
        if width <= 0:
            raise ValueError("decoded audio is empty")
        rolling = sum(rms[:width])
        best = rolling
        best_index = 0
        for index in range(width, len(rms)):
            rolling += rms[index] - rms[index - width]
            if rolling > best:
                best = rolling
                best_index = index - width + 1
        return range_start + float(best_index)

    def _transcode(self, source: str | Path, target: Path, *, start: float, duration: float | None, strip_initial_silence: bool) -> None:
        fade_duration = self.validate_full(Path(source))['duration'] if duration is None else duration
        bitrate = re.fullmatch(r"(\d+(?:\.\d+)?)([kKmM]?)", self.bitrate)
        if bitrate:
            rate = float(bitrate[1]) * {'': 1, 'k': 1000, 'm': 1000000}[bitrate[2].lower()]
            if fade_duration * rate / 8 > MAX_AUDIO_BYTES:
                raise AudioSizeLimitError('complete track exceeds 64 MiB media budget')
        filters: list[str] = []
        if strip_initial_silence:
            filters.append("silenceremove=start_periods=1:start_silence=0:start_threshold=-45dB")
        filters.extend([
            "loudnorm=I=-16:LRA=11:TP=-1.5",
            "afade=t=in:st=0:d=0.5",
            f"afade=t=out:st={max(0, fade_duration - 1)}:d=1",
        ])
        command = ["ffmpeg", "-v", "error", "-y"]
        if start:
            command.extend(["-ss", f"{start:.3f}"])
        command.extend(["-i", str(source), "-vn"])
        if duration is not None:
            command.extend(["-t", f"{duration:.3f}"])
        command.extend([
            "-af", ",".join(filters),
            "-codec:a", "libmp3lame", "-b:a", self.bitrate,
            # Stop runaway output, then reject it rather than publish a size-trimmed track.
            "-fs", str(MAX_AUDIO_BYTES + 1), str(target),
        ])
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=600)
        if target.stat().st_size > MAX_AUDIO_BYTES:
            target.unlink()
            raise AudioSizeLimitError('complete track exceeds 64 MiB media budget')

    def validate(self, path: Path, *, min_duration: float | None = None, max_duration: float | None = None) -> dict:
        if path.stat().st_size > MAX_AUDIO_BYTES:
            raise AudioSizeLimitError('audio exceeds 64 MiB media budget')
        command = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
            "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(path),
        ]
        import json
        payload = json.loads(subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30).stdout)
        duration = float(payload.get("format", {}).get("duration") or 0)
        size = int(payload.get("format", {}).get("size") or 0)
        if not any(stream.get("codec_type") == "audio" for stream in payload.get("streams", [])):
            raise ValueError("output has no audio stream")
        minimum = self.target_seconds - 2 if min_duration is None else min_duration
        maximum = self.target_seconds + 2 if max_duration is None else max_duration
        if not math.isfinite(duration) or duration < minimum or duration > maximum:
            raise ValueError(f"output duration out of range: {duration:.2f}")
        if size > MAX_AUDIO_BYTES:
            raise AudioSizeLimitError('audio exceeds 64 MiB media budget')
        if size < 4096:
            raise ValueError("output audio is unexpectedly small")
        return {"duration": duration, "size": size, "sha256": sha256(path)}

    def atomic_replace_owned(self, prepared: Path, target: Path, expected_sha256: str, backup: Path) -> tuple[str, str]:
        if prepared.stat().st_size > MAX_AUDIO_BYTES:
            raise AudioSizeLimitError('audio exceeds 64 MiB media budget')
        with theme_file_guard(target):
            if target.is_symlink():
                raise PermissionError('theme symlinks are not managed')
            if not target.exists() or sha256(target) != expected_sha256:
                raise RuntimeError('theme changed since it was audited')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                durable_copy(target, backup)
            if sha256(backup) != expected_sha256:
                raise RuntimeError('backup hash mismatch')
            digest = install_prepared(prepared, target, 'replacement')
        return digest, str(backup)

    def restore_replacement(self, target: Path, backup: Path, expected_new_sha256: str, expected_old_sha256: str) -> bool:
        with theme_file_guard(target):
            if target.is_symlink() or not target.exists() or sha256(target) != expected_new_sha256:
                return False
            if sha256(backup) != expected_old_sha256:
                raise RuntimeError('backup hash mismatch')
            durable_copy(backup, target)
            return True

    def atomic_commit(self, prepared: Path, target_dir: Path) -> tuple[bool, Path, str]:
        if prepared.stat().st_size > MAX_AUDIO_BYTES:
            raise AudioSizeLimitError('audio exceeds 64 MiB media budget')
        target_dir.mkdir(parents=False, exist_ok=True)
        target = target_dir / 'theme.mp3'
        with theme_file_guard(target):
            if target.is_symlink():
                raise PermissionError('theme symlinks are not managed')
            if target.exists():
                return False, target, sha256(target)
            digest = install_prepared(prepared, target, 'tmp')
        return True, target, digest


@contextmanager
def theme_file_guard(target: Path):
    # Stable lock inode; never unlink while another process may be waiting.
    with (target.parent / '.theme.mp3.lock').open('a+b') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        yield


def install_prepared(prepared: Path, target: Path, kind: str) -> str:
    """Caller holds the theme-file guard and has checked ownership/no-overwrite."""
    temp = target.parent / f'.theme.{os.getpid()}.{kind}.mp3'
    try:
        shutil.copyfile(prepared, temp)
        with temp.open('rb') as handle:
            os.fsync(handle.fileno())
        os.replace(temp, target)
        sync_directory(target.parent)
        return sha256(target)
    finally:
        temp.unlink(missing_ok=True)


def sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_copy(source: Path, target: Path) -> None:
    fd, name = tempfile.mkstemp(prefix=".theme-copy-", dir=target.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as source_file:
            shutil.copyfileobj(source_file, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, target)
        sync_directory(target.parent)
    finally:
        temp.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def temporary_directory() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix="emby-theme-")
