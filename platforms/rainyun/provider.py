"""Load only the exact reviewed external image solver and browser script."""

import hashlib
import json
from pathlib import Path
import types

DIRECTORY = Path(__file__).resolve().parent


def read_provider(root):
    root = Path(root)
    manifest = json.loads((DIRECTORY / "provider-source.json").read_text())
    verified = {}
    for name, digest in manifest["runtime_files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("upstream_missing")
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("dependency_incompatible")
        verified[name] = raw
    module = types.ModuleType("_benefits_rainyun_icr")
    module.__file__ = str(root / "ICR.py")
    # Compile the bytes already checked, not a second mutable file read.
    exec(compile(verified["ICR.py"], module.__file__, "exec"), module.__dict__)
    return module.main, verified["stealth.min.js"].decode("utf-8")
