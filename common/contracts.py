"""Read-only exact-file pin checks before importing external upstream code."""

import hashlib
from pathlib import Path


def verify_files(root, files):
    root = Path(root).resolve()
    if not root.is_dir():
        return "upstream_missing"
    for name, digest in files.items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            return "upstream_missing"
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() != digest:
            return "dependency_incompatible"
    return None
