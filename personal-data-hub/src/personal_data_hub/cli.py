from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta

from .contracts import canonical, instant, utcnow
from .collection_errors import error_detail
from .runner import configuration, run, store_from


def main():
    parser = argparse.ArgumentParser(description="个人信息采集与归档")
    parser.add_argument("--config")
    parser.add_argument('--skip-schema-init', action='store_true', help='调度父进程已初始化数据库，子任务直接使用现有表')
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("collect", "backfill", "reconcile"):
        p = sub.add_parser(action); p.add_argument("source", nargs="?", default="all"); p.add_argument("--since")
    sub.add_parser("status"); sub.add_parser("serve-collectors"); sub.add_parser("backfill-previews")
    sub.add_parser("processing-status")
    p = sub.add_parser("process-pending"); p.add_argument("--limit", type=int, default=50); p.add_argument('--lane', choices=('reading', 'model'), default='reading'); p.add_argument('--max-seconds', type=int)
    p = sub.add_parser("rebuild-content"); p.add_argument("--source"); p.add_argument("--force", action="store_true"); p.add_argument("--after"); p.add_argument("--limit", type=int, default=250, help="每个事务的扫描条数"); p.add_argument("--one-page", action="store_true")
    p.add_argument('--background-page', action='store_true', help='后台单页回填；在同一事务保存进度')
    from .processing.registry import PROFILES
    p.add_argument('--processor', choices=sorted(PROFILES))
    p = sub.add_parser("backfill-display"); p.add_argument("--rebuild", action="store_true"); p.add_argument("--kind")
    p = sub.add_parser("backup"); p.add_argument("--destination", required=True)
    p = sub.add_parser("ack-skysight"); p.add_argument("--source", choices=["skysight-raw", "skysight-summaries"], required=True); p.add_argument("--relative", required=True); p.add_argument("--expected-hash", required=True)
    p = sub.add_parser("traffic-remaining"); p.add_argument("--url")
    args = parser.parse_args()
    if args.action == "traffic-remaining":
        from .traffic_remaining import fetch_remaining_traffic
        print(canonical(fetch_remaining_traffic(url=args.url))); return
    config = configuration(args.config)
    store = store_from(config, initialize=not args.skip_schema_init)
    if args.action == "process-pending":
        from .processing.worker import drain
        result = drain(store, args.limit, lane=args.lane, config=config, max_seconds=args.max_seconds)
        print(canonical(result))
        if result['failed']: raise SystemExit(1)
        return
    if args.action in ("processing-status", "rebuild-content"):
        from .processing.repository import ProcessingRepository
        repository = ProcessingRepository(store)
        if args.action == "processing-status":
            print(canonical(repository.status())); return
        after = args.after
        while True:
            result = repository.rebuild(args.source, args.force, after, args.limit, processor=args.processor, background_page=args.background_page)
            print(canonical(result), flush=True)
            if args.one_page or args.background_page or result['next_after'] is None: break
            after = result['next_after']
        return
    if args.action == "backfill-display":
        print(canonical({"display_created": store.backfill_display(rebuild=args.rebuild, kind=args.kind)})); return
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
    if args.action == "serve-collectors":
        from .scheduler import serve
        serve(store, config, args.config)
        return
    selected = list(config["sources"]) if args.source == "all" else [args.source]
    failed = False
    for source in selected:
        settings = config["sources"][source]
        if args.action == "reconcile":
            settings = dict(settings)
            settings["force_full"] = True
        if settings["adapter"] in {"crm", "crm_pg"} or not settings.get("enabled", True): continue
        since = instant(args.since) if args.since else (utcnow() - timedelta(days=30) if args.action == "backfill" else None)
        try:
            result = run(store, source, settings, since)
            print(canonical(result))
            failed = failed or bool(result.get('invalid'))
        except Exception as e:
            failed = True; print(canonical({"source": source, "status": "failed", "error": error_detail(e)}), file=sys.stderr)
    if failed: raise SystemExit(1)
