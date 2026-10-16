from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager, nullcontext
from pathlib import Path

from . import adapters
from .models import Bill, Conflict, HealthData, HealthDay, NotFound, canonical, day, merge_health, now, utc

BILL_COLUMNS = tuple(Bill.model_fields)
SCHEMA = """
CREATE TABLE IF NOT EXISTS health_days(date TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bills(
 id TEXT PRIMARY KEY, source TEXT NOT NULL, source_id TEXT,
 occurred_at TEXT NOT NULL, type TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL,
 fee TEXT NOT NULL, book TEXT, category TEXT, account_from TEXT, account_to TEXT,
 merchant TEXT, item TEXT, note TEXT, tags TEXT NOT NULL, status TEXT NOT NULL,
 updated_at TEXT NOT NULL, UNIQUE(source,source_id));
CREATE INDEX IF NOT EXISTS bills_time ON bills(occurred_at,id);
CREATE TABLE IF NOT EXISTS source_status(source TEXT PRIMARY KEY, last_received_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        created = not self.path.exists()
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise RuntimeError("database schema is newer than this service")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("BEGIN IMMEDIATE;" + SCHEMA + "PRAGMA user_version=1;COMMIT;")
        finally:
            db.close()
        if created:
            self.path.chmod(0o600)

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def integrity(self):
        with self.connection() as db:
            return db.execute("PRAGMA quick_check").fetchone()[0]

    def backup(self, destination: str | Path):
        target = Path(destination).resolve()
        if target.exists() or target == self.path:
            raise Conflict("backup destination already exists")
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.path) as source, sqlite3.connect(target) as output:
            source.backup(output)
        target.chmod(0o600)

    @staticmethod
    def health_row(row):
        return {"date": row["date"], **json.loads(row["data"]), "updated_at": row["updated_at"]}

    @staticmethod
    def bill_row(row):
        value = dict(row)
        value["tags"] = json.loads(value["tags"])
        return value

    def get_health(self, selected: str):
        with self.connection() as db:
            row = db.execute("SELECT * FROM health_days WHERE date=?", (day(selected),)).fetchone()
        if row is None:
            raise NotFound("health day not found")
        return self.health_row(row)

    def create_health(self, record: dict):
        obj = HealthDay.model_validate(record)
        data = merge_health({}, obj.data())
        try:
            with self.connection(write=True) as db:
                stamp = now()
                db.execute("INSERT INTO health_days VALUES(?,?,?)", (obj.date, canonical(data), stamp))
        except sqlite3.IntegrityError:
            raise Conflict("health day already exists") from None
        return {"date": obj.date, **data, "updated_at": stamp}

    def update_health(self, selected: str, patch: dict):
        selected = day(selected)
        if not isinstance(patch, dict) or set(patch) - set(HealthData.model_fields):
            raise ValueError("health patch contains unknown or immutable fields")
        parsed = HealthData.model_validate(patch).data()
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM health_days WHERE date=?", (selected,)).fetchone()
            if row is None:
                raise NotFound("health day not found")
            data = json.loads(row["data"])
            for key in patch:
                if patch[key] is None:
                    data.pop(key, None)
                else:
                    # Public PATCH replaces arrays; only source ingestion merges them.
                    data[key] = merge_health({}, {key: parsed[key]})[key]
            stamp = now()
            db.execute("UPDATE health_days SET data=?,updated_at=? WHERE date=?", (canonical(data), stamp, selected))
        return {"date": selected, **data, "updated_at": stamp}

    def delete_health(self, selected: str):
        with self.connection(write=True) as db:
            changed = db.execute("DELETE FROM health_days WHERE date=?", (day(selected),)).rowcount
        return {"deleted": bool(changed)}

    def get_bill(self, identifier: str):
        with self.connection() as db:
            row = db.execute("SELECT * FROM bills WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise NotFound("bill not found")
        return self.bill_row(row)

    @staticmethod
    def write_bill(db, obj: Bill, stamp: str, *, replace=False):
        value = obj.model_dump()
        value["tags"] = canonical(value["tags"])
        value["updated_at"] = stamp
        columns = (*BILL_COLUMNS, "updated_at")
        # Column names only come from the internal model, never from request data.
        if replace:
            db.execute("UPDATE bills SET " + ",".join(f"{key}=?" for key in columns if key != "id") + " WHERE id=?", [value[key] for key in columns if key != "id"] + [obj.id])
        else:
            db.execute("INSERT INTO bills(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ")", [value[key] for key in columns])

    def create_bill(self, record: dict):
        obj = Bill.model_validate(record)
        try:
            with self.connection(write=True) as db:
                stamp = now()
                self.write_bill(db, obj, stamp)
        except sqlite3.IntegrityError:
            raise Conflict("bill identity already exists") from None
        return {**obj.model_dump(), "updated_at": stamp}

    def update_bill(self, identifier: str, patch: dict):
        if not isinstance(patch, dict) or set(patch) - (set(BILL_COLUMNS) - {"id", "source", "source_id"}):
            raise ValueError("bill patch contains unknown or immutable fields")
        with self.connection(write=True) as db:
            row = db.execute("SELECT * FROM bills WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise NotFound("bill not found")
            value = self.bill_row(row)
            value.pop("updated_at")
            obj = Bill.model_validate({**value, **patch})
            stamp = now()
            self.write_bill(db, obj, stamp, replace=True)
        return {**obj.model_dump(), "updated_at": stamp}

    def delete_bill(self, identifier: str):
        with self.connection(write=True) as db:
            changed = db.execute("DELETE FROM bills WHERE id=?", (identifier,)).rowcount
        return {"deleted": bool(changed)}

    def ingest(self, source: str, payload, *, received_at: str | None = None):
        if source == "health":
            return self.ingest_prepared(source, health_days=adapters.health(payload), received_at=received_at)
        if source == "autoaccounting":
            return self.ingest_prepared(source, bills=[adapters.bill(payload)], received_at=received_at)
        raise NotFound("unknown source")

    def ingest_prepared(self, source: str, *, health_days=None, bills=(), received_at=None, connection=None):
        stamp = utc(received_at) if received_at else now()
        health_days = health_days or {}
        counts = dict(created=0, updated=0, unchanged=0)
        with (self.connection(write=True) if connection is None else nullcontext(connection)) as db:
            for selected, data in health_days.items():
                row = db.execute("SELECT data FROM health_days WHERE date=?", (selected,)).fetchone()
                combined = merge_health(json.loads(row["data"]) if row else {}, data)
                encoded = canonical(combined)
                if row and row["data"] == encoded:
                    counts["unchanged"] += 1
                elif row:
                    db.execute("UPDATE health_days SET data=?,updated_at=? WHERE date=?", (encoded, stamp, selected))
                    counts["updated"] += 1
                else:
                    db.execute("INSERT INTO health_days VALUES(?,?,?)", (selected, encoded, stamp))
                    counts["created"] += 1
            for obj in bills:
                row = db.execute("SELECT * FROM bills WHERE source=? AND source_id=?", (obj.source, obj.source_id)).fetchone()
                if row:
                    previous = self.bill_row(row)
                    previous.pop("updated_at")
                    obj = obj.model_copy(update={"id": row["id"]})
                    if previous == obj.model_dump():
                        counts["unchanged"] += 1
                        continue
                self.write_bill(db, obj, stamp, replace=row is not None)
                counts["updated" if row else "created"] += 1
            db.execute("INSERT INTO source_status VALUES(?,?) ON CONFLICT(source) DO UPDATE SET last_received_at=max(last_received_at,excluded.last_received_at)", (source, stamp))
        return {"ok": True, "committed": True, **counts}

    def source_status(self):
        with self.connection() as db:
            rows = {r["source"]: dict(r) for r in db.execute("SELECT * FROM source_status")}
        return [{"source": name, "last_received_at": rows.get(name, {}).get("last_received_at")} for name in ("health", "autoaccounting")]
