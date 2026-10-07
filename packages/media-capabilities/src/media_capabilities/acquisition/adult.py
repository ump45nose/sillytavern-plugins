"""Pure classification helpers for Adult collection workflows."""

from __future__ import annotations

from pathlib import PurePosixPath

from .javdb_cli import normalize_jav_number


def path_under(path: str, root: str) -> bool:
    try:
        PurePosixPath(path).relative_to(PurePosixPath(root))
        return True
    except ValueError:
        return False


def classify_adult(title: str, path: str, studios=(), *,
                   jav_root: str = "/Adult/JAV",
                   western_root: str = "/Adult/Western",
                   vixen_markers=("vixen",)) -> str | None:
    if path_under(path, jav_root):
        try:
            normalize_jav_number(" ".join((title, PurePosixPath(path).name)))
            return "jav"
        except ValueError:
            return None
    if path_under(path, western_root):
        haystack = " ".join((title, path, *(str(v) for v in studios))).casefold()
        if any(str(marker).casefold() in haystack for marker in vixen_markers):
            return "vixen"
    return None


def collection_path(path: str, root: str, collection: str = "Collection") -> str:
    source = PurePosixPath(path)
    base = PurePosixPath(root)
    try:
        relative = source.relative_to(base)
    except ValueError as exc:
        raise ValueError("媒体文件不在配置的媒体库目录下") from exc
    if relative.parts and relative.parts[0].casefold() == collection.casefold():
        return str(source)
    return str(base / collection / relative)
