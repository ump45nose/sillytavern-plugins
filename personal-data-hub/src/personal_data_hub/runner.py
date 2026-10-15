from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert, update

from .contracts import Batch, Record, canonical, instant, utcnow
from .collection_errors import error_detail, isolated_error
from .storage import Store, runs


def configuration(path=None):
    import os
    p = Path(path or os.environ.get("HUB_CONFIG", "/home/yuwk/.config/personal-data-hub/config.json"))
    return json.loads(p.read_text())


def store_from(config, *, initialize=True):
    import os
    url = config.get("database_url") or os.environ.get("HUB_DATABASE_URL")
    if not url: raise ValueError("database_url_missing")
    return Store(url, config["asset_root"], initialize=initialize)


def adapter(settings):
    from .collectors import BillsCollector, FilesCollector, MemosCollector, PlaudCollector, SQLiteCollector, TokenCollector, PostgreSQLCrmCollector
    from .remote import GoogleCollector, EmailCollector, Mem0Collector, GitCollector
    from .nas_activity import EmbyCollector, NavidromeCollector
    name = settings["adapter"]
    classes = {"crm_pg": PostgreSQLCrmCollector, "crm": SQLiteCollector, "health": SQLiteCollector, "shellcrash": SQLiteCollector, "memos": MemosCollector, "plaud": PlaudCollector, "bills": BillsCollector, "skysight": FilesCollector, "files": FilesCollector, "token": TokenCollector, "google": GoogleCollector, "email": EmailCollector, "mem0": Mem0Collector, "git": GitCollector, "emby": EmbyCollector, "navidrome": NavidromeCollector}
    return classes[name](settings)


def run(store, source, settings, since=None):
    store.register(source, settings.get("account", "owner"), settings["adapter"], settings.get("deletion_support", "explicit_only"))
    rid = str(uuid4())
    totals = dict(changed=0, duplicates=0, tombstoned=0, deleted=0)
    invalid = 0
    with store.lock("source:" + source):
        with store.engine.begin() as c:
            # Acquiring the source lock proves any previous running worker is
            # gone. Preserve its history and finish the interrupted run.
            c.execute(update(runs).where(runs.c.source == source, runs.c.status == "running").values(
                ended_at=utcnow(), status="failed", error=canonical({"type": "InterruptedError", "reason": "上次采集进程中断，已自动重新采集"})))
            c.execute(insert(runs).values(id=rid, source=source, started_at=utcnow(), status="running", records=0))
        try:
            pending = Batch()
            cursor = None
            if settings.get("run_as"):
                import subprocess, sys
                config_path = settings.get("config_path") or os.environ.get("HUB_CONFIG", "/home/yuwk/.config/personal-data-hub/config.json")
                process = subprocess.run(["sudo", "-n", "-u", settings["run_as"], str(Path(sys.executable).parent / "hub"), "--config", config_path, "export-source", source, "--cursor-stdin"], input=canonical({"cursor": {} if settings.get("force_full") else store.cursor(source), "since": since}), capture_output=True, text=True, timeout=300)
                if process.returncode: raise isolated_error(process.stderr)
                batches = []
                for line in process.stdout.split('\n'):
                    if not line.strip():
                        continue
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
                    result = store.ingest(source, pending, refresh_unchanged=False)
                    for key in totals: totals[key] += result[key]
                    pending = Batch()
            pending.next_cursor = cursor
            result = store.ingest(source, pending, refresh_unchanged=False)
            for key in totals: totals[key] += result[key]
        except Exception as exc:
            with store.engine.begin() as c:
                c.execute(update(runs).where(runs.c.id == rid).values(ended_at=utcnow(), status="failed", records=totals["changed"], error=canonical(error_detail(exc))))
            raise
        with store.engine.begin() as c:
            # 本轮校验异常影响采集状态；水位中的历史异常另由 status 报告，不能令成功运行永久 partial。
            c.execute(update(runs).where(runs.c.id == rid).values(ended_at=utcnow(), status="partial" if invalid else "ok", records=totals["changed"], error="segment_invalid" if invalid else None))
    return {"source": source, "invalid": invalid, "historical_invalid": len((cursor or {}).get("invalid_ids", [])), **totals}
