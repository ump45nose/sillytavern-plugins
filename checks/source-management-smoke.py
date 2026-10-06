"""Verify monorepo ownership and compatibility paths without changing services."""
from pathlib import Path
import argparse
import importlib.util
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def build_guard():
    spec = importlib.util.spec_from_file_location("usage_build", ROOT / "apps/usage-monitor/scripts/prepare_build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        def git(*args):
            return subprocess.check_output(["git", *args], cwd=repo, stderr=subprocess.DEVNULL, text=True).strip()
        git("init", "-q")
        git("config", "user.name", "Source smoke")
        git("config", "user.email", "smoke@localhost")
        (repo / "src/usage_monitor_mcp").mkdir(parents=True)
        (repo / "src/usage_monitor_mcp/__init__.py").write_text("version = 1\n")
        for name in ["pyproject.toml", "uv.lock"]:
            (repo / name).write_text("fixture\n")
        git("add", ".")
        git("commit", "-qm", "Original standalone package")
        baseline = git("rev-parse", "HEAD")
        target = repo / "apps/usage-monitor"
        target.mkdir(parents=True)
        for name in ["src", "pyproject.toml", "uv.lock"]:
            (repo / name).rename(target / name)
        git("add", "-A")
        git("commit", "-qm", "Move into monorepo")
        moved = git("rev-parse", "HEAD")
        module.ROOT = target
        assert module.source_changes(baseline, moved) == []
        assert module.source_changes(moved, moved) == []
        (target / "src/usage_monitor_mcp/__init__.py").write_text("version = 2\n")
        git("add", "-A")
        git("commit", "-qm", "Change package")
        changed = git("rev-parse", "HEAD")
        assert module.source_changes(baseline, changed) == ["src/usage_monitor_mcp"]
        assert module.source_changes(moved, changed) == ["src/usage_monitor_mcp"]
    print("monorepo_build_guard_ok standalone_and_prefixed_baselines=true stale_wheel_rejected=true")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployed-nas", action="store_true")
    args = parser.parse_args()
    origins = json.loads((ROOT / "integrations/source-origins.json").read_text())
    for name, origin in origins.items():
        managed = origin["managed_at"]
        for path in managed if isinstance(managed, list) else [managed]:
            assert (ROOT / path).exists(), (name, path)
        if name in {"personal-crm", "usage-monitor-mcp", "hermes-cron-reports"}:
            subprocess.run(["git", "merge-base", "--is-ancestor", origin["commit"], "main"], cwd=ROOT, check=True)
    assert not list((ROOT / "apps").glob("*/.git"))
    assert not list((ROOT / "legacy").glob("*/.git"))
    build_guard()
    if args.deployed_nas:
        backup = Path("/vol1/1000/personal-data-hub/source-backups/20261007-consolidation")
        receipt = json.loads((backup / "receipt.json").read_text())
        for entry in receipt["entries"]:
            path, target = Path(entry["source"]), Path(entry["managed_at"])
            if entry.get("old_source_entry_removed"):
                assert not path.exists() and not path.is_symlink(), str(path)
            else:
                assert path.is_symlink() and path.resolve() == target.resolve(), str(path)
            assert target.resolve().is_relative_to(ROOT), str(target)
            if entry["backup"]:
                assert Path(entry["backup"]).exists(), entry["backup"]
        private = ["apps/crm/.venv", "apps/crm/dist", "apps/usage-monitor/dist",
                   "collectors/plaud/.venv",
                   "legacy/plaud/.venv", "legacy/plaud/config.yaml", "legacy/plaud/daily-v3.yaml"]
        for rel in private:
            path = ROOT / rel
            assert path.is_symlink() and path.exists() and not path.resolve().is_relative_to(ROOT), rel
            subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT, check=True)
        removed = sum(bool(e.get("old_source_entry_removed")) for e in receipt["entries"])
        print(f"nas_source_paths_ok managed_entries={len(receipt['entries'])} old_projects_removed={removed} private_runtimes=external")
    print(f"source_management_smoke_ok projects={len(origins)} imported_history=preserved")


if __name__ == "__main__":
    main()
