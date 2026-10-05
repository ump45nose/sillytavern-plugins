"""Decode BT facts once, without applying a download or quality policy."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class TorrentMetadata:
    info_hash: str
    files: tuple[tuple[str, int], ...]
    private: bool


def parse_metadata(content: bytes) -> TorrentMetadata:
    import bencode

    if not content or len(content) > 10 * 1024 * 1024:
        raise ValueError('种子文件为空或过大')
    root = bencode.bdecode(content, decode=0)
    if not isinstance(root, dict):
        raise ValueError('不是有效的种子文件')

    def field(value, name, default=None):
        return value.get(name.encode(), value.get(name, default))

    def decoded(value):
        return value.decode('utf-8', 'replace') if isinstance(value, bytes) else str(value)

    info = field(root, 'info')
    if not isinstance(info, dict):
        raise ValueError('无效的种子元数据')
    rows = field(info, 'files')
    if rows is not None:
        if not isinstance(rows, list) or not rows:
            raise ValueError('种子缺少文件清单')
        files = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('种子文件条目无效')
            parts = field(row, 'path.utf-8') or field(row, 'path')
            if not isinstance(parts, list) or not parts:
                raise ValueError('种子文件路径无效')
            files.append(('/'.join(decoded(part) for part in parts), int(field(row, 'length', -1))))
    else:
        name = field(info, 'name.utf-8') or field(info, 'name')
        if name is None:
            raise ValueError('种子缺少文件清单')
        files = [(decoded(name), int(field(info, 'length', -1)))]
    return TorrentMetadata(hashlib.sha1(bencode.bencode(info)).hexdigest(), tuple(files),
                            bool(field(info, 'private', 0)))
