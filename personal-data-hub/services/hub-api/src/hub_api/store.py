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
                CREATE TABLE IF NOT EXISTS login_pending (
                    id_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS login_pending_expiry ON login_pending(expires);
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

    def document(self, name):
        import json
        with self.connection() as db:
            row = db.execute('SELECT * FROM documents WHERE name=?', (name,)).fetchone()
        return {'version':row['version'],'updated_at':row['updated_at'],'document':json.loads(row['document'])} if row else None

    def put_document(self, name, document, expected, now):
        import json
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM documents WHERE name=?', (name,)).fetchone()
            version = row['version'] if row else 0
            if expected is not None and version != expected:
                current = {'version':version,'updated_at':row['updated_at'],'document':json.loads(row['document'])} if row else None
                return False, current
            db.execute('INSERT INTO documents VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,document=excluded.document',
                       (name,version+1,now,encoded))
        return True, {'version':version+1,'updated_at':now,'document':document}

    def observe_attention(self, active, scopes, now):
        """Resolve only conditions whose source was observed; failed reads are not recovery."""
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT id FROM attention_state').fetchall():
                if row['id'].split(':',1)[0] in scopes and row['id'] not in active:
                    db.execute('DELETE FROM attention_state WHERE id=?',(row['id'],))
            for identifier, since in active.items():
                db.execute('INSERT OR IGNORE INTO attention_state(id,since) VALUES (?,?)',(identifier,since or now))
            return {r['id']:dict(r) for r in db.execute('SELECT * FROM attention_state')}

    def handle_attention(self, identifier, until=None):
        with self.connection() as db:
            if until is None:
                return db.execute('UPDATE attention_state SET dismissed=1,snooze_until=NULL WHERE id=?',(identifier,)).rowcount > 0
            return db.execute('UPDATE attention_state SET dismissed=0,snooze_until=? WHERE id=?',(until,identifier)).rowcount > 0

    def save_login(self, kind, identifier, payload, expires, now):
        import json
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_pending WHERE expires<=?',(now,))
            if db.execute('SELECT count(*) FROM login_pending').fetchone()[0]>=1000:
                return False
            db.execute('INSERT INTO login_pending VALUES (?,?,?,?)',(self.digest(identifier),kind,json.dumps(payload),expires))
        return True

    def consume_login(self, kind, identifier, now):
        import json
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT payload,expires FROM login_pending WHERE id_hash=? AND kind=?',(self.digest(identifier),kind)).fetchone()
            db.execute('DELETE FROM login_pending WHERE id_hash=? OR expires<=?',(self.digest(identifier),now))
        return json.loads(row['payload']) if row and row['expires']>now else None

    def exchange_device(self, code, challenge, now, timestamp):
        import hmac
        import json
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT payload,expires FROM login_pending WHERE id_hash=? AND kind='exchange'",(self.digest(code),)).fetchone()
            db.execute('DELETE FROM login_pending WHERE id_hash=? OR expires<=?',(self.digest(code),timestamp))
            if not row or row['expires']<=timestamp: return None
            payload=json.loads(row['payload'])
            if not hmac.compare_digest(payload['challenge'],challenge): return None
            token=secrets.token_urlsafe(32);identifier=str(uuid4())
            db.execute('INSERT INTO devices VALUES (?,?,?,?,?)',(identifier,payload['device_name'],self.digest(token),now,now))
        return {'device_id':identifier,'token':token}
