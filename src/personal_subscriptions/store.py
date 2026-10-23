import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .models import Conflict, NotFound, Reading, Subscription
from .brands import BRANDS, icon_url


def utcnow(): return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, database):
        self.database = str(database)
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                  id TEXT PRIMARY KEY, version INTEGER NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observations (
                  subscription_id TEXT PRIMARY KEY REFERENCES subscriptions(id) ON DELETE CASCADE,
                  reading TEXT, last_success_at TEXT, last_attempt_at TEXT NOT NULL, error TEXT);
                CREATE TABLE IF NOT EXISTS source_accounts (
                  source TEXT PRIMARY KEY, observed_at TEXT NOT NULL, document TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db: yield db
        finally: db.close()

    def unpack(self, row, db):
        if row is None: raise NotFound("subscription not found")
        item = dict(row)
        item.update(Subscription.model_validate_json(item.pop("document")).model_dump(mode="json"))
        item["icon_url"] = icon_url(item["service_key"])
        if item["theme_color"] is None and item["service_key"] in BRANDS:
            item["theme_color"] = BRANDS[item["service_key"]][1]
        monthly = None
        if item["price"] is not None and item["cycle"] in ("day", "week", "month", "year"):
            factors = {"day": Decimal(365)/12, "week": Decimal(52)/12, "month": Decimal(1), "year": Decimal(1)/12}
            monthly = (Decimal(item["price"]) * factors[item["cycle"]] / item["frequency"]).quantize(Decimal("0.01"))
        item["monthly_equivalent"] = str(monthly) if monthly is not None else None
        obs = db.execute("SELECT * FROM observations WHERE subscription_id=?", (item["id"],)).fetchone()
        item["quota"] = None
        if obs:
            quota = dict(obs)
            quota.pop("subscription_id")
            reading = json.loads(quota.pop("reading")) if quota.get("reading") else None
            quota["reading"] = reading
            stale = True
            if reading:
                instant = datetime.fromisoformat(reading["observed_at"].replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - instant).total_seconds()
                stale = reading["stale"] or not 0 <= age <= reading["valid_for_seconds"]
            quota["status"] = "error" if quota["error"] else ("stale" if stale else "ok")
            quota["stale"] = stale
            item["quota"] = quota
        return item

    def get(self, identifier):
        with self.connect() as db:
            return self.unpack(db.execute("SELECT * FROM subscriptions WHERE id=?", (identifier,)).fetchone(), db)

    def list(self, offset=0, limit=50, category=None):
        if not 0 <= offset or not 1 <= limit <= 200: raise ValueError("invalid pagination")
        if category and category not in ("ai", "network", "membership", "other"): raise ValueError("invalid category")
        with self.connect() as db:
            condition, params = (" WHERE json_extract(document,'$.category')=?", [category]) if category else ("", [])
            total = db.execute("SELECT count(*) FROM subscriptions" + condition, params).fetchone()[0]
            rows = db.execute("SELECT * FROM subscriptions" + condition + " ORDER BY created_at,id LIMIT ? OFFSET ?", params+[limit, offset]).fetchall()
            return {"items": [self.unpack(r, db) for r in rows], "total": total,
                    "next_offset": offset+len(rows) if offset+len(rows) < total else None}

    def create(self, record, identifier=None):
        record = Subscription.model_validate(record)
        identifier = identifier or str(uuid4())
        with self.connect() as db:
            try:
                db.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?)", (identifier, 1, utcnow(), utcnow(), record.model_dump_json()))
            except sqlite3.IntegrityError: raise Conflict("subscription already exists") from None
        return self.get(identifier)

    def update(self, identifier, patch, version):
        if not isinstance(version, int) or isinstance(version, bool) or version < 1: raise ValueError("version required")
        if not patch or set(patch) - set(Subscription.model_fields): raise ValueError("invalid patch fields")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM subscriptions WHERE id=?", (identifier,)).fetchone()
            if row is None: raise NotFound("subscription not found")
            if row["version"] != version: raise Conflict("subscription changed; reload before editing")
            previous = json.loads(row["document"])
            updated = Subscription.model_validate({**previous, **patch}).model_dump(mode="json")
            db.execute("UPDATE subscriptions SET document=?, version=version+1, updated_at=? WHERE id=?", (json.dumps(updated), utcnow(), identifier))
            if updated["binding"] != previous["binding"] or not updated["active"]:
                db.execute("DELETE FROM observations WHERE subscription_id=?", (identifier,))
        return self.get(identifier)

    def delete(self, identifier, version):
        if not isinstance(version, int) or isinstance(version, bool) or version < 1: raise ValueError("version required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT version FROM subscriptions WHERE id=?", (identifier,)).fetchone()
            if row is None: raise NotFound("subscription not found")
            if row[0] != version: raise Conflict("subscription changed; reload before deleting")
            db.execute("DELETE FROM subscriptions WHERE id=?", (identifier,))
        return {"deleted": True, "id": identifier}

    def observe(self, identifier, binding, reading=None, error=None):
        if reading is not None: reading = Reading.model_validate(reading).model_dump_json()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT document FROM subscriptions WHERE id=?", (identifier,)).fetchone()
            # A slow collection must not reattach data after an edit or resurrect a deleted record.
            current = json.loads(row[0]) if row else None
            if not current or current["binding"] != binding or not current["active"]: return False
            attempted = utcnow()
            if reading is not None:
                db.execute("INSERT INTO observations VALUES (?,?,?,?,NULL) ON CONFLICT(subscription_id) DO UPDATE SET reading=excluded.reading,last_success_at=excluded.last_success_at,last_attempt_at=excluded.last_attempt_at,error=NULL", (identifier, reading, attempted, attempted))
            else:
                db.execute("INSERT INTO observations VALUES (?,NULL,NULL,?,?) ON CONFLICT(subscription_id) DO UPDATE SET last_attempt_at=excluded.last_attempt_at,error=excluded.error", (identifier, attempted, error or "unavailable"))
        return True

    def integrity(self):
        with self.connect() as db: return db.execute("PRAGMA quick_check").fetchone()[0]

    def summary(self):
        items, offset = [], 0
        while True:
            page = self.list(offset, 200)
            items.extend(page["items"])
            if page["next_offset"] is None: break
            offset = page["next_offset"]
        totals = {}
        for item in items:
            if item["active"] and item["payer"] == "self" and item["monthly_equivalent"] is not None:
                totals[item["currency"]] = totals.get(item["currency"], Decimal(0)) + Decimal(item["monthly_equivalent"])
        return {"items": items, "monthly_by_currency": {k: str(v) for k,v in sorted(totals.items())},
                "unclassified_payer_count": sum(x["active"] and x["payer"] == "unknown" for x in items)}

    def catalog(self, source=None, items=None):
        with self.connect() as db:
            if source is not None:
                db.execute("INSERT INTO source_accounts VALUES (?,?,?) ON CONFLICT(source) DO UPDATE SET observed_at=excluded.observed_at,document=excluded.document", (source, utcnow(), json.dumps(items)))
            return {"sources": [{"source": r["source"], "checked_at": r["observed_at"], "accounts": json.loads(r["document"])} for r in db.execute("SELECT * FROM source_accounts ORDER BY source")]}

    def backup(self, destination):
        path = Path(destination)
        with path.open("xb"): pass
        path.chmod(0o600)
        with self.connect() as source, sqlite3.connect(path) as target: source.backup(target)
