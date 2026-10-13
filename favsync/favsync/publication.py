"""Small single-file acceptance and publication primitives.

Bundle formats still own their richer validators and multi-file semantics.
"""
import os
from pathlib import Path

from .common import SyncError


def accepted_size(path, *, error="download_missing_file"):
    """Apply the same minimum acceptance to recovered and fresh artifacts."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise SyncError(error)
    size = path.stat().st_size
    if not size:
        raise SyncError(error)
    return size


def publish_file(downloaded, final):
    """Publish on the staging filesystem atomically, never replacing a target."""
    downloaded, final = Path(downloaded), Path(final)
    accepted_size(downloaded)
    with downloaded.open("rb") as stream:
        os.fsync(stream.fileno())
    try:
        os.link(downloaded, final)
    except FileExistsError:
        raise SyncError("destination_exists") from None
    # Persist the directory entry before a caller commits completion to SQLite.
    directory_fd = os.open(final.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    downloaded.unlink()
    return accepted_size(final)
