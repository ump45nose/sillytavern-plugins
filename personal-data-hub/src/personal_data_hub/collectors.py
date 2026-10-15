"""本地采集适配器；业务分析与模型处理不在这里执行。"""
from __future__ import annotations

import json
import mimetypes
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .contracts import Asset, Batch, Record, digest, instant, utcnow


@contextmanager
def snapshot(path):
    """SQLite backup API 包含 WAL，读取不干扰源写入。"""
    source = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    target = sqlite3.connect(":memory:")
    target.row_factory = sqlite3.Row
    try:
        source.backup(target)
        yield target
    finally:
        source.close(); target.close()


def file_asset(path):
    p = Path(path)
    return Asset(p.name, path=p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream")


def chunks(items, size=250):
    buffer = []
    for item in items:
        buffer.append(item)
        if len(buffer) == size:
            yield Batch(records=buffer)
            buffer = []
    if buffer:
        yield Batch(records=buffer)


class SQLiteCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        kind = self.settings["adapter"]
        seen = []
        with snapshot(self.settings["path"]) as c:
            if kind == "crm":
                tables = ["people", "interactions", "facts", "reminders", "sync_clients"]
            elif kind == "health":
                tables = ["health_payloads"]
            else:
                tables = ["traffic_hourly", "collector_gaps", "collector_meta"]
            for table in tables:
                items = []
                statement = f'SELECT * FROM "{table}"'
                params = ()
                if table == "traffic_hourly" and cursor.get("collected_at"):
                    from datetime import timedelta
                    since_bucket = (utcnow() - timedelta(hours=3)).astimezone(__import__("zoneinfo").ZoneInfo(self.settings.get("timezone", "Asia/Shanghai"))).strftime("%Y-%m-%dT%H:00")
                    statement += " WHERE bucket >= ?"; params = (since_bucket,)
                for row in c.execute(statement, params):
                    raw = dict(row)
                    for name in ("aliases", "organizations", "contact_methods", "tags", "payload_json"):
                        if isinstance(raw.get(name), str): raw[name] = json.loads(raw[name])
                    if table == "traffic_hourly":
                        eid = "hour:" + digest({k: v for k, v in raw.items() if k not in ("upload_bytes", "download_bytes")})
                    elif table == "sync_clients": eid = "client:" + digest([raw["source"], raw["client_id"]])
                    else: eid = table + ":" + str(raw.get("id", raw.get("key")))
                    seen.append(eid)
                    event = raw.get("occurred_at", raw.get("observed_at", raw.get("received_at", raw.get("bucket", raw.get("started_at", raw.get("created_at"))))))
                    if table == "traffic_hourly" and event:
                        parsed = datetime.fromisoformat(event)
                        if parsed.tzinfo is None: event = parsed.replace(tzinfo=__import__("zoneinfo").ZoneInfo(self.settings.get("timezone", "Asia/Shanghai")))
                    normal = {"table": table}
                    if table == "traffic_hourly": normal.update(upload_bytes=raw["upload_bytes"], download_bytes=raw["download_bytes"], grain="hour+destination+process+route", cumulative=True)
                    if table == "health_payloads": normal.update(payload=raw["payload_json"], missing_is_zero=False)
                    items.append(Record(eid, table, raw, normal, instant(event), instant(raw.get("updated_at"))))
                    if len(items) == 250:
                        yield Batch(records=items); items = []
                if items: yield Batch(records=items)
        # Health 的历史 webhook 快照和流量保留窗口缺失不代表设备删除。
        yield Batch(next_cursor={"collected_at": utcnow().isoformat()}, authoritative=kind == "crm", seen_ids=seen if kind == "crm" else None)


class FilesCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        root = Path(self.settings["path"])
        if not root.is_dir(): raise FileNotFoundError("source_directory_missing")
        seen = []
        adapter = self.settings["adapter"]
        fingerprints = dict(cursor.get("files", {}))
        invalid_ids = set(cursor.get("invalid_ids", []))
        revalidate = cursor.get("segment_validator_version") != 3
        patterns = self.settings.get("patterns", ["**/*.json", "**/*.md", "**/*.jsonl"])
        paths = sorted({p for pattern in patterns for p in root.glob(pattern) if p.is_file() and not p.name.startswith(".")})
        for p in paths:
            relative = str(p.relative_to(root))
            try:
                stat = p.stat()
                fingerprint = [stat.st_size, stat.st_mtime_ns]
                if adapter == "skysight" and p.name == "metadata.json":
                    for extra in sorted(p.parent.glob("*")):
                        if extra.is_file():
                            x = extra.stat(); fingerprint.extend([extra.name, x.st_size, x.st_mtime_ns])
                if fingerprints.get(relative) == fingerprint and not (revalidate and relative in invalid_ids): continue
                content = p.read_bytes()
            except FileNotFoundError:
                continue  # 执行报告可能在枚举后轮转；已有归档保留。
            raw = {"path": relative}
            normal = {}
            occurred = None
            if adapter == "skysight" and p.name == "metadata.json":
                events = p.parent / "events.jsonl"
                attachments = [file_asset(x) for x in p.parent.glob("*") if x.is_file()]
                try:
                    raw.update(json.loads(p.read_text()))
                    if raw.get("endedAt") is None: continue
                    if not events.is_file(): raise ValueError("events_missing")
                    # JSON strings may legally contain Unicode line separators.
                    # JSONL records are delimited only by LF, not splitlines().
                    rows = [json.loads(x) for x in events.read_text().split("\n") if x.strip()]
                    if raw.get("eventCount") is not None and raw["eventCount"] != len(rows): raise ValueError("event_count_mismatch")
                    normal = {"events": rows, "source_ref": relative, "closed": True}
                    occurred = instant(raw.get("startedAt"))
                    record_kind = "computer_segment"
                    invalid_ids.discard(relative)
                except (ValueError, OSError) as error:
                    # 历史 NAS 副本不全时保留原始文件与异常标记；不阻断其余已闭合片段。
                    reason = str(error) if str(error) in {'events_missing', 'event_count_mismatch'} else type(error).__name__
                    normal = {"validation_error": reason, "source_ref": relative}
                    record_kind = "computer_segment_invalid"
                    invalid_ids.add(relative)
            else:
                attachments = [Asset(p.name, content=content, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream")]
                record_kind = self.settings.get("kind", "source_artifact")
                if adapter == "skysight":
                    if not p.name.endswith("-memory-summary.md"): continue
                    normal = {"content": content.decode(), "interval": "6h" if "6h" in p.name else "10min", "source_ref": relative}
                    record_kind = "computer_summary"
                    # 官方文件名的 UTC 时间用于事件时间，mtime 仅表示文件变化。
                    import re
                    m = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})", p.name)
                    if m: occurred = datetime.strptime(m[1], "%Y-%m-%dT%H-%M-%S").replace(tzinfo=utcnow().tzinfo)
                elif p.suffix == ".json":
                    raw["document"] = json.loads(content)
                elif p.suffix in (".md", ".txt"):
                    normal["content"] = content.decode()
            eid = relative; seen.append(eid)
            fingerprints[relative] = fingerprint
            # mtime 是可变附件的版本元数据；事件时间缺失保持为空。
            yield Batch(records=[Record(eid, record_kind, raw, normal, occurred, instant(stat.st_mtime), assets=attachments)])
        # NAS/Mac 的缓存轮转不意味着源删除，只有显式删除事件才清理。
        yield Batch(next_cursor={"collected_at": utcnow().isoformat(), "files": fingerprints, "invalid_ids": sorted(invalid_ids), "segment_validator_version": 3})


class BillsCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        root = Path(self.settings["path"])
        if not root.is_dir(): raise FileNotFoundError("bills_directory_missing")
        for p in sorted((root / "bills").glob("*.jsonl")):
            rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
            for row in rows:
                payload = row.get("bill", row.get("payload", row))
                bid = payload.get("id", row.get("bill_id"))
                if bid is None: raise ValueError("bill_id_missing")
                yield Batch(records=[Record(str(bid), "bill", row, {"currency": payload.get("currency"), "amount": str(payload.get("money", payload.get("amount", ""))), "source_ref": str(bid)}, instant(payload.get("time", 0) / 1000) if isinstance(payload.get("time"), (int, float)) else None)])
        yield Batch(next_cursor={"collected_at": utcnow().isoformat()})


class PlaudCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        if self.settings.get("sync_command"):
            import subprocess
            result = subprocess.run(self.settings["sync_command"], capture_output=True, text=True, timeout=600)
            if result.returncode: raise RuntimeError("plaud_sync_failed")
        root = Path(self.settings["path"])
        from .plaud_content import PlaudContent
        content = PlaudContent(root, self.settings.get("timezone", "Asia/Shanghai"))
        with snapshot(root / "state/state.db") as c:
            for row in c.execute("SELECT * FROM recordings"):
                raw = dict(row)
                attachments = []
                if raw.get("local_path"):
                    p = Path(raw["local_path"])
                    if not p.is_file(): raise RuntimeError("plaud_recording_missing")
                    attachments.append(file_asset(p))
                normal = {"duration_ms": raw["duration_ms"], "date": raw["local_date"], "download_state": raw["remote_state"], **content.recording(raw)}
                yield Batch(records=[Record(raw["recording_id"], "recording", raw, normal, instant(raw["start_at"]), instant(raw["updated_at"]), assets=attachments)])
        yield from chunks(content.extra_records)
        for directory in ("raw", "work", "output", "daily-v3", "gold", "experiments"):
            if (root / directory).is_dir():
                yield from FilesCollector({"adapter": "files", "path": str(root), "kind": "recording_artifact", "patterns": [directory + "/**/*.json", directory + "/**/*.jsonl", directory + "/**/*.md", directory + "/**/*.wav"]}).collect({})
        yield Batch(next_cursor={"collected_at": utcnow().isoformat()})
