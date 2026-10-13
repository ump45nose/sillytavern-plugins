"""Build a pinned, import-safe external Rewards dependency tree. Never run a task."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.contracts import verify_files

ROOT = Path(__file__).resolve().parent
MARKER = "\nasync function main(): Promise<void> {"


def patch_entry(source):
    if source.count(MARKER) != 1 or "\nmain().catch(async error => {" not in source:
        raise ValueError("unsupported_entrypoint")
    # Keep the exported class/context; remove only autonomous CLI setup/invocation.
    source = source.split(MARKER)[0] + "\n"
    source = source.replace("import { checkNodeVersion } from './util/Validator'\n", "")
    return source.replace("import Utils, { isBrowserClosedError }", "import Utils")


def stage(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    manifest = json.loads((ROOT / "build-source.json").read_text())
    error = verify_files(source, manifest["files"])
    if error:
        raise ValueError(error)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination_must_be_empty")
    destination.mkdir(parents=True, exist_ok=True)
    for name in manifest["files"]:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    entry = destination / "src/index.ts"
    entry.write_text(patch_entry(entry.read_text()))
    return destination


def attest(destination):
    destination = Path(destination)
    files = {}
    for path in sorted((destination / "dist").rglob("*")):
        if path.is_file():
            files[str(path.relative_to(destination))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    if "dist/index.js" not in files:
        raise ValueError("build_output_missing")
    files["package.json"] = hashlib.sha256(
        (destination / "package.json").read_bytes()
    ).hexdigest()
    files["package-lock.json"] = hashlib.sha256(
        (destination / "package-lock.json").read_bytes()
    ).hexdigest()
    value = {
        "protocol": 1,
        "source_commit": "f61f4e982bbb435f37133bed0dc5b4c582ed1e73",
        "entrypoint": "dist/index.js",
        "patch": "Remove autonomous CLI main; preserve exported bot and executionContext",
        "compiler_arguments": ["--module", "Node20", "--moduleResolution", "Node16"],
        "node_version": subprocess.check_output(
            ["node", "--version"], text=True
        ).strip(),
        "typescript_version": json.loads(
            (destination / "node_modules/typescript/package.json").read_text()
        )["version"],
        "files": files,
    }
    (destination / "benefits-build.json").write_text(json.dumps(value, indent=2) + "\n")
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path)
    p.add_argument("destination", type=Path)
    p.add_argument("--install-build", action="store_true")
    args = p.parse_args()
    destination = stage(args.source, args.destination)
    if args.install_build:
        import os

        env = {**os.environ, "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}
        subprocess.run(
            ["npm", "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=destination,
            env=env,
            check=True,
        )
        # Official config combines commonjs with bundler resolution; Node20 supports the pinned Node24 runtime and ESM dependency imports.
        subprocess.run(
            [
                "node",
                "node_modules/typescript/bin/tsc",
                "--module",
                "Node20",
                "--moduleResolution",
                "Node16",
            ],
            cwd=destination,
            check=True,
        )
        subprocess.run(
            ["node", "scripts/main/copyAssets.js"], cwd=destination, check=True
        )
        attest(destination)
    print("Staged import-safe Rewards source; no account task executed")


if __name__ == "__main__":
    main()
