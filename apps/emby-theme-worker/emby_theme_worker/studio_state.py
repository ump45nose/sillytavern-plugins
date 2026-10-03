"""Studio state is separate from legacy execution status and media sidecars."""
from __future__ import annotations
import fcntl
import json
import uuid
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS controls (
 emby_id TEXT PRIMARY KEY, locked INTEGER NOT NULL DEFAULT 0,
 quality TEXT, extraction TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS diagnostics (
 id INTEGER PRIMARY KEY, emby_id TEXT, stage TEXT NOT NULL, provider TEXT,
 outcome TEXT NOT NULL, evidence TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS studio_jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, item_id TEXT, payload TEXT NOT NULL,
 status TEXT NOT NULL, result TEXT, error TEXT, priority INTEGER NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (
 id INTEGER PRIMARY KEY, emby_id TEXT NOT NULL, candidate_hash TEXT NOT NULL,
 verdict TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS library_snapshot (
 emby_id TEXT PRIMARY KEY, payload TEXT NOT NULL, present INTEGER NOT NULL DEFAULT 1);
"""

class StudioState:
    def commit_application(self, item, replacement, digest, target, registered):
        from .db import now
        stamp = now()
        status = 'complete' if registered else 'pending_refresh'
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''INSERT INTO items(emby_id,name,item_type,path,provider_ids,status,source_provider,score,output_path,output_sha256,updated_at)
                VALUES(?,?,?,?,?,?, 'manual',100,?,?,?) ON CONFLICT(emby_id) DO UPDATE SET status=excluded.status,source_provider='manual',score=100,output_path=excluded.output_path,output_sha256=excluded.output_sha256,updated_at=excluded.updated_at''',
                (item.id,item.name,item.item_type,item.path,json.dumps(item.provider_ids),status,str(target),digest,stamp))
            conn.execute("INSERT INTO controls VALUES(?,?,'manual',NULL,?) ON CONFLICT(emby_id) DO UPDATE SET locked=excluded.locked,quality='manual',updated_at=excluded.updated_at", (item.id,registered,stamp))
            conn.execute('UPDATE replacements SET status=?,finished_at=? WHERE id=?', (status,stamp,replacement))

    @contextmanager
    def item_guard(self, item_id: str):
        import hashlib
        directory = self.path.parent / "locks"
        directory.mkdir(exist_ok=True)
        with (directory / hashlib.sha256(item_id.encode()).hexdigest()).open("a+b") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield

    def control(self, item_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM controls WHERE emby_id=?", (item_id,)).fetchone()
            return dict(row) if row else {"locked": False, "quality": None}

    def set_control(self, item_id: str, *, locked=None, quality=None, extraction=None) -> None:
        from .db import now
        with self.connect() as conn:
            conn.execute("INSERT INTO controls VALUES(?,COALESCE(?,0),?,?,?) ON CONFLICT(emby_id) DO UPDATE SET locked=COALESCE(?,locked),quality=COALESCE(?,quality),extraction=COALESCE(?,extraction),updated_at=excluded.updated_at",
                         (item_id, locked, quality, json.dumps(extraction) if extraction else None, now(), locked, quality, json.dumps(extraction) if extraction else None))

    def diagnostic(self, item_id: str, stage: str, provider: str, outcome: str, evidence=None) -> None:
        from .db import now
        from .security import redact
        def clean(value):
            if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
            if isinstance(value,list):return [clean(v) for v in value]
            return redact(value) if isinstance(value,str) else value
        with self.connect() as conn:
            conn.execute("INSERT INTO diagnostics(emby_id,stage,provider,outcome,evidence,created_at) VALUES(?,?,?,?,?,?)",
                         (item_id, stage, provider, outcome, json.dumps(clean(evidence or {}), ensure_ascii=False), now()))

    def diagnostics(self, item_id: str) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM diagnostics WHERE emby_id=? ORDER BY id DESC LIMIT 300", (item_id,))]

    def enqueue(self, kind: str, item_id: str | None, payload: dict, priority: int = 0) -> str:
        from .db import now
        identity = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT id FROM studio_jobs WHERE kind=? AND item_id IS ? AND status IN ('queued','running')", (kind, item_id)).fetchone()
            if existing and priority > 0:
                return existing["id"]
            conn.execute("INSERT INTO studio_jobs VALUES(?,?,?,?, 'queued',NULL,NULL,?,?,?)", (identity, kind, item_id, json.dumps(payload), priority, now(), now()))
        return identity

    def claim_job(self, allow_automatic: bool = True) -> dict | None:
        from .db import now
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM studio_jobs WHERE status='queued' AND (? OR priority=0) ORDER BY priority,created_at LIMIT 1", (allow_automatic,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE studio_jobs SET status='running',updated_at=? WHERE id=?", (now(), row["id"]))
            return dict(row)

    def finish_job(self, identity: str, result=None, error=None) -> None:
        from .db import now
        with self.connect() as conn:
            conn.execute("UPDATE studio_jobs SET status=?,result=?,error=?,updated_at=? WHERE id=?", ("failed" if error else "complete", json.dumps(result, ensure_ascii=False), error, now(), identity))

    def jobs(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id,kind,item_id,status,result,error,created_at,updated_at,payload FROM studio_jobs ORDER BY created_at DESC LIMIT 100")
            output = []
            for row in rows:
                value = dict(row)
                payload = json.loads(value.pop('payload') or '{}')
                # Connect an existing preview to its result card without exposing
                # source URLs or replaying downloads whenever the page is opened.
                value['candidate_id'] = payload.get('candidate_id')
                output.append(value)
            return output
