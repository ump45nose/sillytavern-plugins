from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta

from .contracts import canonical, instant, utcnow
from .runner import configuration, run, store_from


def main():
    parser = argparse.ArgumentParser(description="个人信息采集与归档")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("collect", "backfill", "reconcile", "import-legacy"):
        p = sub.add_parser(action); p.add_argument("source", nargs="?", default="all"); p.add_argument("--since")
    sub.add_parser("status"); sub.add_parser("serve-collectors"); sub.add_parser("backfill-previews")
    p = sub.add_parser("import-crm"); p.add_argument("path")
    p = sub.add_parser("export-source"); p.add_argument("source", choices=["google"]); p.add_argument("--cursor-stdin", action="store_true")
    p = sub.add_parser("backup"); p.add_argument("--destination", required=True)
    p = sub.add_parser("ack-skysight"); p.add_argument("--source", choices=["skysight-raw", "skysight-summaries"], required=True); p.add_argument("--relative", required=True); p.add_argument("--expected-hash", required=True)
    args = parser.parse_args()
    config = configuration(args.config)
    if args.action == "export-source":
        from dataclasses import asdict
        from .runner import adapter
        request = json.load(sys.stdin) if args.cursor_stdin else {}
        for batch in adapter(config["sources"][args.source]).collect(request.get("cursor", {}), instant(request.get("since"))):
            if any(r.assets for r in batch.records): raise ValueError("isolated_source_assets_unsupported")
            print(canonical(asdict(batch)), flush=True)
        return
    store = store_from(config)
    if args.action == "backfill-previews":
        print(canonical({"previews_created": store.backfill_previews()})); return
    if args.action == "backup":
        from .migration import backup
        print(canonical(backup(store, args.destination))); return
    if args.action == "ack-skysight":
        from pathlib import Path
        import hashlib
        from .collectors import FilesCollector
        settings = dict(config["sources"][args.source]); root = Path(settings["path"]).resolve(); p = (root / args.relative).resolve()
        if not p.is_relative_to(root) or not p.is_file(): raise ValueError("invalid_skysight_path")
        if args.source == "skysight-raw":
            if p.name != "metadata.json": raise ValueError("invalid_segment_metadata")
            original = p.parent / "metadata.source.json"
            paths = [("metadata.json", original if original.exists() else p), ("events.jsonl", p.parent / "events.jsonl")]
        else: paths = [(p.name, p)]
        h = hashlib.sha256()
        for name, path in paths: h.update(name.encode()); h.update(path.read_bytes())
        if h.hexdigest() != args.expected_hash: raise ValueError("skysight_manifest_mismatch")
        settings["patterns"] = [args.relative]
        batches = list(FilesCollector(settings).collect({}))
        if not any(r.kind in ("computer_segment", "computer_summary") for b in batches for r in b.records): raise ValueError("skysight_segment_not_ready")
        with store.lock("source:" + args.source):
            for batch in batches:
                batch.next_cursor = None
                store.ingest(args.source, batch)
        print(canonical({"committed": True, "sha256": args.expected_hash})); return
    if args.action == "status": print(canonical(store.status())); return
    if args.action == "import-crm":
        from .migration import import_crm
        print(canonical(import_crm(store, args.path))); return
    if args.action == "serve-collectors":
        deadlines = {}
        while True:
            now = time.monotonic()
            for source, settings in config["sources"].items():
                if not settings.get("enabled", True) or now < deadlines.get(source, 0): continue
                try: print(canonical(run(store, source, settings)), flush=True)
                except Exception as e: print(canonical({"source": source, "status": "failed", "error": type(e).__name__}), flush=True)
                deadlines[source] = time.monotonic() + int(settings.get("interval_seconds", 3600))
            time.sleep(5)
    selected = list(config["sources"]) if args.source == "all" else [args.source]
    failed = False
    for source in selected:
        settings = config["sources"][source]
        if args.action in ("import-legacy", "reconcile"):
            settings = dict(settings)
            settings["force_full"] = True
        if not settings.get("enabled", True): continue
        since = instant(args.since) if args.since else (utcnow() - timedelta(days=30) if args.action == "backfill" else None)
        try: print(canonical(run(store, source, settings, since)))
        except Exception as e:
            failed = True; print(canonical({"source": source, "status": "failed", "error": type(e).__name__}), file=sys.stderr)
    if failed: raise SystemExit(1)
