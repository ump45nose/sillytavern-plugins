"""Read-only file evidence for BT resources; magnet lookup never fetches video pieces."""

from __future__ import annotations

import base64
import html
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

from .selection import inspect_files
from .torrent_metadata import parse_metadata


@dataclass(frozen=True)
class FileEvidence:
    info_hash: str
    files: tuple[str, ...]
    video_bytes: int
    total_bytes: int
    private: bool


def _video_size(files: tuple[tuple[str, int], ...]) -> int:
    return sum(size for name, size in files
               if PurePosixPath(name.replace('\\', '/')).suffix.casefold() in {'.mkv', '.mp4'})


def _validated(info_hash: str, files: tuple[tuple[str, int], ...], private: bool,
               title: str, expected_episodes: set[int] | None) -> FileEvidence:
    names = tuple(name for name, _ in files)
    okay, reason = inspect_files(title, list(names), expected_episodes)
    if not okay:
        raise ValueError(reason)
    if any(size < 0 for _, size in files):
        raise ValueError('文件大小无效')
    video_bytes = _video_size(files)
    if not video_bytes:
        raise ValueError('无法核实视频文件大小')
    return FileEvidence(info_hash.lower(), names, video_bytes,
                        sum(size for _, size in files), private)


def torrent_evidence(content: bytes, title: str,
                     expected_episodes: set[int] | None = None) -> FileEvidence:
    metadata = parse_metadata(content)
    return _validated(metadata.info_hash, metadata.files, metadata.private,
                      title, expected_episodes)



def normalize_magnet(magnet: str) -> str:
    # Some pages double-escape href attributes, leaving literal &amp;tr keys.
    for _ in range(2):
        decoded = html.unescape(magnet)
        if decoded == magnet:
            break
        magnet = decoded
    magnet = magnet.strip()
    if urlparse(magnet).scheme.casefold() != 'magnet':
        raise ValueError('不是磁力链接')
    return magnet


def magnet_hash(magnet: str) -> str:
    magnet = normalize_magnet(magnet)
    xt = parse_qs(urlparse(magnet).query).get('xt', [''])[0]
    value = xt.removeprefix('urn:btih:')
    if re.fullmatch(r'[A-Z2-7]{32}', value, re.I):
        value = base64.b32decode(value.upper()).hex()
    if not re.fullmatch(r'[0-9a-fA-F]{40}', value):
        raise ValueError('磁力链接没有可核实的 v1 info-hash')
    return value.lower()


def magnet_evidence(magnet: str, title: str, expected_episodes: set[int] | None = None,
                    timeout: int = 45) -> FileEvidence:
    """Fetch BitTorrent metadata in upload mode; never request movie pieces."""
    magnet = normalize_magnet(magnet)
    expected_hash = magnet_hash(magnet)
    deps = '/config/filmwatchlist-deps'
    if deps not in sys.path:
        sys.path.insert(0, deps)
    try:
        import libtorrent as lt
    except ImportError as exc:
        raise ValueError('未安装磁力元数据预检依赖') from exc
    with tempfile.TemporaryDirectory(prefix='filmwatchlist-metadata-') as target:
        session = lt.session({
            'listen_interfaces': '0.0.0.0:0', 'enable_dht': True,
            'enable_lsd': False, 'enable_upnp': False, 'enable_natpmp': False,
        })
        handle = lt.add_magnet_uri(session, magnet, {
            'save_path': target, 'flags': lt.torrent_flags.upload_mode,
        })
        try:
            until = time.monotonic() + max(1, min(int(timeout), 90))
            while not handle.has_metadata() and time.monotonic() < until:
                time.sleep(0.5)
            if not handle.has_metadata():
                raise ValueError('磁力元数据预检超时')
            info = handle.get_torrent_info()
            digest = str(info.info_hashes().v1).lower()
            if digest != expected_hash:
                raise ValueError('磁力元数据 info-hash 不一致')
            storage = info.files()
            files = tuple((storage.file_path(i), int(storage.file_size(i)))
                          for i in range(storage.num_files()))
            return _validated(digest, files, bool(info.priv()), title, expected_episodes)
        finally:
            session.remove_torrent(handle, lt.options_t.delete_files)
