import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL, last_seen TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    name TEXT PRIMARY KEY, version INTEGER NOT NULL, updated_at TEXT NOT NULL,
                    document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attention_state (
                    id TEXT PRIMARY KEY, since TEXT NOT NULL, dismissed INTEGER NOT NULL DEFAULT 0,
                    snooze_until TEXT
                );
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def issue_device(self, name, now):
        token = secrets.token_urlsafe(32)
        identifier = str(uuid4())
        with self.connection() as db:
            db.execute("INSERT INTO devices VALUES (?,?,?,?,?)", (identifier, name, self.digest(token), now, now))
        return {"device_id": identifier, "token": token}

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, token, now):
        with self.connection() as db:
            row = db.execute("SELECT id,last_seen FROM devices WHERE token_hash=?", (self.digest(token),)).fetchone()
            if row:
                # Minute-level writes, rather than a write on every module request.
                if row["last_seen"][:16] != now[:16]:
                    db.execute("UPDATE devices SET last_seen=? WHERE id=?", (now, row["id"]))
                return row["id"]
        return None

    def devices(self):
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT id,name,created_at,last_seen FROM devices ORDER BY created_at")]

    def revoke(self, identifier):
        with self.connection() as db:
            return db.execute("DELETE FROM devices WHERE id=?", (identifier,)).rowcount > 0
