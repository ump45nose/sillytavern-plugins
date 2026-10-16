"""One-way, read-only Hub import into a NEW database, with independent storage audit."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections import Counter
from decimal import Decimal
from pathlib import Path

from . import adapters
from .models import SCALARS, business_day, canonical, date_window, sample_key, utc
from .store import Store


class Audit:
    """Disk-backed expectation set; never holds or persists source upload packages."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript("""
            CREATE TABLE measures(day TEXT,metric TEXT,identity TEXT,value TEXT,PRIMARY KEY(day,metric,identity));
            CREATE TABLE bills(source TEXT,source_id TEXT,value TEXT,PRIMARY KEY(source,source_id));
        """)

    def health(self, days):
        for selected, data in days.items():
            for metric, value in data.items():
                rows = [(selected, metric, "", canonical(value))] if metric in SCALARS else [(selected, metric, sample_key(v), canonical(v)) for v in value]
                self.db.executemany("INSERT INTO measures VALUES(?,?,?,?) ON CONFLICT(day,metric,identity) DO UPDATE SET value=excluded.value", rows)

    def bill(self, obj):
        self.db.execute("INSERT INTO bills VALUES(?,?,?) ON CONFLICT(source,source_id) DO UPDATE SET value=excluded.value", (obj.source, obj.source_id, canonical(obj.model_dump())))

    def verify(self, store):
        expected_days = self.db.execute("SELECT count(DISTINCT day) FROM measures").fetchone()[0]
        expected_bills = self.db.execute("SELECT count(*) FROM bills").fetchone()[0]
        measured, health_hash, bill_hash = 0, hashlib.sha256(), hashlib.sha256()
        with store.connection() as actual:
            if not (actual.execute("SELECT count(*) FROM health_days").fetchone()[0] == expected_days): raise ValueError("health day count differs")
            if not (actual.execute("SELECT count(*) FROM bills").fetchone()[0] == expected_bills): raise ValueError("bill count differs")
            for row in actual.execute("SELECT date,data FROM health_days ORDER BY date"):
                entries = {}
                for metric, identity, encoded in self.db.execute("SELECT metric,identity,value FROM measures WHERE day=? ORDER BY metric,identity", (row["date"],)):
                    entries.setdefault(metric, {})[identity] = encoded
                data = json.loads(row["data"])
                if not (set(data) == set(entries)): raise ValueError("health metric fields differ")
                for metric, value in data.items():
                    values = {"": canonical(value)} if metric in SCALARS else {sample_key(v): canonical(v) for v in value}
                    if not (values == entries[metric]): raise ValueError("health sample identity or business fields differ")
                    if not (metric in SCALARS or len(value) == len(values)): raise ValueError("duplicate health samples")
                    measured += len(values)
                    for identity, encoded in sorted(values.items()):
                        health_hash.update(canonical([row["date"], metric, identity, encoded]).encode())
            for row in actual.execute("SELECT * FROM bills ORDER BY source,source_id"):
                value = store.bill_row(row); value.pop("updated_at")
                encoded = canonical(value)
                expected = self.db.execute("SELECT value FROM bills WHERE source=? AND source_id=?", (row["source"], row["source_id"])).fetchone()
                if not (expected and encoded == expected[0]): raise ValueError("bill business fields differ")
                bill_hash.update(encoded.encode())
        return {"health_days": expected_days, "health_values_and_samples": measured, "bills": expected_bills,
            "health_sha256": health_hash.hexdigest(), "bills_sha256": bill_hash.hexdigest(), "verified": True}

    def close(self): self.db.close()


def import_rows(rows, store, audit):
    """Accept a streaming row iterator, useful both for PostgreSQL and isolated fixtures."""
    counts = Counter()
    with store.connection(write=True) as target:
        for row in rows:
            source, raw = row["source"], row["raw"]
            try:
                if source == "health":
                    payload = raw["payload_json"]
                    if isinstance(payload, str): payload = json.loads(payload, parse_float=Decimal)
                    # Two July Huawei daily summaries predate the current source format.
                    # User chose not to extend the business model for their un-timed aggregates.
                    if payload.get("date") and not payload.get("timestamp") and isinstance(payload.get("steps"), int):
                        selected = business_day(payload["date"])
                        start, end = date_window(selected, selected)
                        counts["legacy_daily_summaries"] += 1
                        for name in ("weight_kg", "sleep_minutes", "heart_rate_avg"):
                            if name in payload: counts["legacy_unmigrated_"+name] += 1
                        payload = {"steps": [{"start_time": start, "end_time": end, "count": payload["steps"]}]}
                    days = adapters.health(payload)
                    audit.health(days)
                    store.ingest_prepared("health", health_days=days, received_at=utc(row["observed_at"]), connection=target)
                else:
                    obj = adapters.bill(raw.get("bill", raw.get("payload", raw)))
                    audit.bill(obj)
                    store.ingest_prepared("autoaccounting", bills=[obj], received_at=utc(row["observed_at"]), connection=target)
                counts[source] += 1
            except Exception as error:
                # Locate the bad record without printing its contents or private DSN.
                raise ValueError(f"migration failed at {source}/{row['external_id']}: {type(error).__name__}") from error
    audit.db.commit()
    return dict(counts)


def migrate_hub(source_config: str, destination: str, report_path: str | None = None):
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import set_json_loads

    path = Path(destination).resolve()
    if path.exists():
        raise ValueError("migration destination must be a new database; existing records are never overwritten")
    config = json.loads(Path(source_config).read_text())
    url = config["database_url"].replace("postgresql+psycopg://", "postgresql://", 1)
    store = Store(path)
    audit = None
    try:
        with tempfile.TemporaryDirectory(prefix="records-audit-") as directory:
            audit = Audit(Path(directory)/"audit.sqlite")
            with psycopg.connect(url, row_factory=dict_row) as source:
                set_json_loads(lambda raw: json.loads(raw, parse_float=Decimal), source)
                source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                with source.cursor(name="records_migration") as rows:
                    rows.itersize = 100
                    rows.execute("SELECT source,external_id,raw,observed_at FROM hub_records WHERE source IN ('health','finance') ORDER BY observed_at,id")
                    counts = import_rows(rows, store, audit)
            report = {"source_records": counts, **audit.verify(store), "database_integrity": store.integrity()}
            audit.close(); audit = None
        if report_path:
            report_file = Path(report_path)
            with report_file.open("x") as out:
                json.dump(report, out, ensure_ascii=False, indent=2)
            report_file.chmod(0o600)
        return report
    except BaseException:
        if audit: audit.close()
        for suffix in ("", "-wal", "-shm"): Path(str(path)+suffix).unlink(missing_ok=True)
        raise
