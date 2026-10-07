"""Build a secret-free, relocatable collection payload for the signed Mac app."""

import gzip
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile

from packaging.requirements import Requirement


def build(app):
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    resources = app / "Contents/Resources"
    resources.mkdir(parents=True, exist_ok=True)
    site = Path(metadata.distribution("chatlog-keeper").locate_file("")).resolve()
    pending = ["httpx", "python-dotenv", "chatlog-keeper[images]"]
    selected = {}
    while pending:
        requirement = Requirement(pending.pop())
        distribution = metadata.distribution(requirement.name)
        name = distribution.metadata["Name"]
        extras = {""} | set(requirement.extras)
        if name in selected:
            continue
        selected[name] = distribution
        for dependency in distribution.requires or []:
            dependency = Requirement(dependency)
            if dependency.marker is None or any(dependency.marker.evaluate({"extra": extra}) for extra in extras):
                pending.append(str(dependency))
    # Only wheel RECORD files enter the artifact; never copy runtime cache/secrets.
    with tempfile.TemporaryDirectory(prefix="agent-payload-", dir=root / "dist") as temporary:
        payload = Path(temporary)
        python = payload / "python"
        shutil.copytree(sys.base_prefix, python, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "share"))
        packages = payload / "packages"
        for distribution in selected.values():
            for relative in distribution.files or []:
                source = Path(distribution.locate_file(relative))
                try:
                    relative = source.resolve().relative_to(site)
                except ValueError:
                    continue  # console scripts and external editable links
                if not source.is_file() or source.suffix == ".pyc" or source.name == "direct_url.json":
                    continue
                target = packages / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        crm = repo / "apps/crm/src/personal_crm"
        (packages / "personal_crm").mkdir(parents=True)
        shutil.copy2(crm / "__init__.py", packages / "personal_crm/__init__.py")
        shutil.copytree(crm / "connector", packages / "personal_crm/connector",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copytree(repo / "agents/mac/skysight", payload / "skysight",
                        ignore=shutil.ignore_patterns("*.plist", "__pycache__"))
        (payload / "run-wechat.py").write_text(
            "from pathlib import Path\nimport sys\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parent / 'packages'))\n"
            "from personal_crm.connector.cli import main\nraise SystemExit(main())\n"
        )
        (payload / "launch-wechat.py").write_text(
            "import subprocess\nimport sys\n"
            "raise SystemExit(subprocess.run(sys.argv[1:], check=False).returncode)\n"
        )
        # Existing pinned reader executable, never its private configuration/data.
        agent = Path.home() / "Library/LaunchAgents/com.personal-crm.wechat.plist"
        import plistlib
        config = plistlib.loads(agent.read_bytes())["EnvironmentVariables"]
        native = Path(config["CHATLOG_EXECUTABLE"]).expanduser()
        native_hash = hashlib.sha256(native.read_bytes()).hexdigest()
        if native_hash != config["CHATLOG_EXPECTED_SHA256"]:
            raise RuntimeError("chatlog_checksum_mismatch")
        (payload / "bin").mkdir()
        shutil.copy2(native, payload / "bin/chatlog-keeper")
        private = Path.home() / "Library/Application Support/PersonalDataHub"
        helper = private / "Personal Data Hub Credentials.app"
        shutil.copytree(helper, payload / helper.name, symlinks=True)
        credential_manifest = json.loads((private / "Signing/credential-reader.json").read_text())
        archive = resources / "collection.tar.gz"
        with archive.open("wb") as output, gzip.GzipFile(fileobj=output, mode="wb", mtime=0, filename="") as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as tar:
                for path in sorted(payload.rglob("*")):
                    info = tar.gettarinfo(str(path), arcname=str(path.relative_to(payload)))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    if info.isfile():
                        with path.open("rb") as source:
                            tar.addfile(info, source)
                    else:
                        tar.addfile(info)
        with archive.open("rb") as source:
            archive_hash = hashlib.file_digest(source, "sha256").hexdigest()
        manifest = {"schema": 1, "archiveSHA256": archive_hash, "pythonVersion": sys.version.split()[0],
                    "chatlogSHA256": native_hash, "credentialReader": credential_manifest,
                    "distributions": {name: dist.version for name, dist in sorted(selected.items())}}
        (resources / "collection.json").write_text(json.dumps(manifest, indent=2))
    shutil.copy2(root / "install-agents.py", resources / "install-agents.py")
    print("Bundled collection code and Python runtime; production state excluded")


if __name__ == "__main__":
    build(Path(sys.argv[1]).resolve())
