from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert, update

from .contracts import Batch, Record, instant, utcnow
from .storage import Store, runs


def configuration(path=None):
    import os
    p = Path(path or os.environ.get("HUB_CONFIG", "/home/yuwk/.config/personal-data-hub/config.json"))
    return json.loads(p.read_text())


def store_from(config):
    import os
    url = config.get("database_url") or os.environ.get("HUB_DATABASE_URL")
    if not url: raise ValueError("database_url_missing")
    return Store(url, config["asset_root"])


def adapter(settings):
    from .collectors import BillsCollector, FilesCollector, MemosCollector, PlaudCollector, SQLiteCollector, TokenCollector, PostgreSQLCrmCollector
    from .remote import GoogleCollector, EmailCollector, Mem0Collector, GitCollector
    name = settings["adapter"]
    classes = {"crm_pg": PostgreSQLCrmCollector, "crm": SQLiteCollector, "health": SQLiteCollector, "shellcrash": SQLiteCollector, "memos": MemosCollector, "plaud": PlaudCollector, "bills": BillsCollector, "skysight": FilesCollector, "files": FilesCollector, "token": TokenCollector, "google": GoogleCollector, "email": EmailCollector, "mem0": Mem0Collector, "git": GitCollector}
    return classes[name](settings)


def run(store, source, settings, since=None):
    store.register(source, settings.get("account", "owner"), settings["adapter"], settings.get("deletion_support", "explicit_only"))
    rid = str(uuid4())
    totals = dict(changed=0, duplicates=0, tombstoned=0, deleted=0)
    invalid = 0
    with store.lock("source:" + source):
        with store.engine.begin() as c:
            c.execute(insert(runs).values(id=rid, source=source, started_at=utcnow(), status="running", records=0))
        try:
            pending = Batch()
            cursor = None
            if settings.get("run_as"):
                import subprocess, sys
                from .contracts import canonical
                config_path = settings.get("config_path") or os.environ.get("HUB_CONFIG", "/home/yuwk/.config/personal-data-hub/config.json")
                process = subprocess.run(["sudo", "-n", "-u", settings["run_as"], str(Path(sys.executable).parent / "hub"), "--config", config_path, "export-source", source, "--cursor-stdin"], input=canonical({"cursor": {} if settings.get("force_full") else store.cursor(source), "since": since}), capture_output=True, text=True, timeout=300)
                if process.returncode: raise RuntimeError("isolated_source_read_failed")
                batches = []
                for line in process.stdout.splitlines():
                    wire = json.loads(line)
                    wire["records"] = [Record(**{**r, "occurred_at": instant(r.get("occurred_at")), "updated_at": instant(r.get("updated_at"))}) for r in wire["records"]]
                    batches.append(Batch(**wire))
            else: batches = adapter(settings).collect({} if settings.get("force_full") else store.cursor(source), since)
            for batch in batches:
                invalid += sum(r.kind == "computer_segment_invalid" for r in batch.records)
                pending.records.extend(batch.records)
                pending.deletions.extend(batch.deletions)
                if batch.next_cursor is not None: cursor = batch.next_cursor
                if len(pending.records) >= 250 or batch.authoritative:
                    pending.authoritative = batch.authoritative
                    pending.seen_ids = batch.seen_ids
                    result = store.ingest(source, pending)
                    for key in totals: totals[key] += result[key]
                    pending = Batch()
            pending.next_cursor = cursor
            result = store.ingest(source, pending)
            for key in totals: totals[key] += result[key]
            if cursor and cursor.get("invalid_ids"): invalid = max(invalid, len(cursor["invalid_ids"]))
        except Exception as exc:
            with store.engine.begin() as c:
                c.execute(update(runs).where(runs.c.id == rid).values(ended_at=utcnow(), status="failed", records=totals["changed"], error=type(exc).__name__))
            raise
        with store.engine.begin() as c:
            c.execute(update(runs).where(runs.c.id == rid).values(ended_at=utcnow(), status="partial" if invalid else "ok", records=totals["changed"], error="historical_segment_invalid" if invalid else None))
    return {"source": source, "invalid": invalid, **totals}
