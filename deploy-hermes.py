#!/usr/bin/env python3
"""Install Hermes cron source and trusted profile compatibility entrypoints."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def atomic_write(target, content, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cron-deploy-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def wrapper(target):
    if target.suffix == ".sh":
        import shlex
        return "#!/usr/bin/env bash\nset -euo pipefail\nexec bash " + shlex.quote(str(target)) + ' "$@"\n'
    return ("#!/usr/bin/env python3\nfrom pathlib import Path\nimport runpy\nimport sys\n"
            f"target = Path({str(target)!r})\n"
            "sys.path.insert(0, str(target.parent))\n"
            "runpy.run_path(str(target), run_name='__main__')\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=Path("/home/yuwk/cron"))
    parser.add_argument("--profile-home", type=Path, default=Path("/home/hermes/.hermes/profiles/lingjun"))
    parser.add_argument("--agent-root", type=Path, default=Path("/home/hermes/.hermes/hermes-agent"))
    parser.add_argument("--review-root", type=Path, default=Path("/vol2/1000/Docker/personal-review"))
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    manifest = json.loads((source / "hermes/manifest.json").read_text())
    local_config = args.runtime / "env/hermes.local.json"
    if local_config.exists():
        # Host deploy resets env/ to 0700; restore only this read boundary.
        subprocess.run(["setfacl", "-m", "u:hermes:--x", str(local_config.parent)], check=True)
        subprocess.run(["setfacl", "-m", "u:hermes:r--", str(local_config)], check=True)
    backup = args.profile_home / "cron/migration-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True, mode=0o700)
    for group in ("hermes", "model", "retired"):
        for path in (source / group).rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            target = args.runtime / path.relative_to(source)
            atomic_write(target, path.read_text(), 0o755 if path.suffix in {".py", ".sh"} else 0o644)
    # Human-run Steam login helpers contain no credentials and are separate
    # from trusted scheduled entrypoints. Installing them never starts a login.
    for name in ("login.py", "prepare.py"):
        atomic_write(args.runtime / "scripts/steam-asf" / name,
                     (source / "steam-asf" / name).read_text(), 0o755)
    for kind, base in (("profile_scripts", args.profile_home / "scripts"),
                       ("agent_scripts", args.agent_root / "scripts"),
                       ("review_scripts", args.review_root / "scripts"),
                       ("review_sources", args.review_root / "review/sources")):
        for name, relative in manifest.get(kind, {}).items():
            old = base / name
            if old.exists():
                saved = backup / kind / name
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old, saved)
                saved.chmod(0o600)
            content = wrapper(args.runtime / relative)
            if kind == "review_sources":
                content = ("from pathlib import Path\nimport runpy\nimport sys\n"
                           f"target = Path({str(args.runtime / relative)!r})\n"
                           "sys.path.insert(0, str(target.parent))\n"
                           "globals().update(runpy.run_path(str(target), run_name=__name__))\n")
            atomic_write(old, content, 0o755)
    print(f"Hermes cron source installed in {args.runtime}; entrypoint backups: {backup}")


if __name__ == "__main__":
    main()
