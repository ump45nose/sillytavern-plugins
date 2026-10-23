"""User-owned Hub state. Business records remain in the upstream services."""
import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


class Store:
    history_limit = 20

    def __init__(self, path: Path, owner=None):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS hub_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL, UNIQUE(issuer,subject))')
            db.execute('INSERT OR IGNORE INTO hub_meta VALUES (?,?)', ('instance_id', str(uuid4())))
            db.execute('INSERT OR IGNORE INTO hub_meta VALUES (?,?)', ('cursor_key', secrets.token_hex(32)))
            configured_owner = self._user(db, *owner) if owner else None
            saved = db.execute("SELECT value FROM hub_meta WHERE key='source_owner'").fetchone()
            if saved and configured_owner and saved['value'] != configured_owner:
                raise ValueError('source owner changed; explicit migration required')
            self.owner_id = saved['value'] if saved else configured_owner
            if self.owner_id:
                db.execute('INSERT OR IGNORE INTO hub_meta VALUES (?,?)', ('source_owner', self.owner_id))
            db.execute('CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, last_seen TEXT NOT NULL, user_id TEXT NOT NULL, revoked_at TEXT)')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(devices)')}
            legacy = 'user_id' not in columns
            old_tables = {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            needs_owner = legacy and db.execute('SELECT count(*) FROM devices').fetchone()[0]
            for table in ('documents', 'attention_state'):
                if table in old_tables and 'user_id' not in {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}:
                    needs_owner = needs_owner or db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
            if needs_owner and not self.owner_id:
                raise ValueError('legacy Hub data requires an explicit owner issuer and subject')
            if legacy:
                db.execute('ALTER TABLE devices ADD COLUMN user_id TEXT')
                db.execute('ALTER TABLE devices ADD COLUMN revoked_at TEXT')
                db.execute('UPDATE devices SET user_id=?', (self.owner_id,))
            for table in ('documents', 'attention_state'):
                if table in old_tables and 'user_id' not in {r['name'] for r in db.execute(f'PRAGMA table_info({table})')}:
                    db.execute(f'ALTER TABLE {table} RENAME TO legacy_{table}')
            db.execute('CREATE TABLE IF NOT EXISTS documents (user_id TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL, document TEXT NOT NULL, updated_by TEXT, PRIMARY KEY(user_id,name))')
            db.execute('CREATE TABLE IF NOT EXISTS document_history (user_id TEXT NOT NULL, name TEXT NOT NULL, version INTEGER NOT NULL, updated_at TEXT NOT NULL, document TEXT NOT NULL, updated_by TEXT, PRIMARY KEY(user_id,name,version))')
            db.execute('CREATE TABLE IF NOT EXISTS attention_state (user_id TEXT NOT NULL, id TEXT NOT NULL, since TEXT NOT NULL, dismissed INTEGER NOT NULL DEFAULT 0, snooze_until TEXT, PRIMARY KEY(user_id,id))')
            if 'documents' in old_tables and db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_documents'").fetchone():
                db.execute('INSERT INTO documents SELECT ?,name,version,updated_at,document,NULL FROM legacy_documents', (self.owner_id,))
                db.execute('DROP TABLE legacy_documents')
            if 'attention_state' in old_tables and db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_attention_state'").fetchone():
                db.execute('INSERT INTO attention_state SELECT ?,id,since,dismissed,snooze_until FROM legacy_attention_state', (self.owner_id,))
                db.execute('DROP TABLE legacy_attention_state')
            db.execute('INSERT OR IGNORE INTO document_history SELECT * FROM documents')
            db.execute('CREATE TABLE IF NOT EXISTS login_pending (id_hash TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS login_pending_expiry ON login_pending(expires)')
            # Pre-upgrade exchange tickets lack a validated identity and cannot mint devices.
            if legacy:
                db.execute('DELETE FROM login_pending')
            db.execute('CREATE TABLE IF NOT EXISTS source_bindings (user_id TEXT PRIMARY KEY, version INTEGER NOT NULL, fingerprint TEXT NOT NULL, document TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS binding_revisions (user_id TEXT NOT NULL, binding_id TEXT NOT NULL, fingerprint TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(user_id,binding_id))')
            db.execute('CREATE TABLE IF NOT EXISTS source_snapshots (user_id TEXT NOT NULL, cache_key TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(user_id,cache_key))')
            self.instance_id = db.execute("SELECT value FROM hub_meta WHERE key='instance_id'").fetchone()['value']
            self.cursor_key = bytes.fromhex(db.execute("SELECT value FROM hub_meta WHERE key='cursor_key'").fetchone()['value'])

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _user(db, issuer, subject):
        db.execute('INSERT OR IGNORE INTO users VALUES (?,?,?)', (str(uuid4()), issuer, subject))
        return db.execute('SELECT id FROM users WHERE issuer=? AND subject=?', (issuer, subject)).fetchone()['id']

    def user(self, issuer, subject):
        with self.connection() as db:
            return self._user(db, issuer, subject)

    def _owner(self, user_id):
        result = user_id or self.owner_id
        if not result:
            raise ValueError('user context required')
        return result

    def issue_device(self, name, now, user_id=None):
        token, identifier = secrets.token_urlsafe(32), str(uuid4())
        with self.connection() as db:
            db.execute('INSERT INTO devices(id,name,token_hash,created_at,last_seen,user_id) VALUES (?,?,?,?,?,?)',
                       (identifier, name, self.digest(token), now, now, self._owner(user_id)))
        return {'device_id': identifier, 'token': token}

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authenticate(self, token, now):
        with self.connection() as db:
            row = db.execute('SELECT id,user_id,last_seen FROM devices WHERE token_hash=? AND revoked_at IS NULL', (self.digest(token),)).fetchone()
            if row and row['user_id']:
                if row['last_seen'][:16] != now[:16]:
                    db.execute('UPDATE devices SET last_seen=? WHERE id=?', (now, row['id']))
                return {'device_id': row['id'], 'user_id': row['user_id']}
        return None

    def devices(self, user_id=None):
        with self.connection() as db:
            if user_id is None and not self.owner_id:
                return []
            return [dict(r) for r in db.execute('SELECT id,name,created_at,last_seen FROM devices WHERE user_id=? AND revoked_at IS NULL ORDER BY created_at', (self._owner(user_id),))]

    def revoke(self, identifier, user_id=None, now='revoked'):
        with self.connection() as db:
            return db.execute('UPDATE devices SET revoked_at=? WHERE id=? AND user_id=? AND revoked_at IS NULL', (now, identifier, self._owner(user_id))).rowcount > 0

    @staticmethod
    def _document(row):
        return {k: row[k] for k in ('version', 'updated_at', 'updated_by')} | {'document': json.loads(row['document'])} if row else None

    def document(self, name, user_id=None):
        if user_id is None and self.owner_id is None:
            return None
        with self.connection() as db:
            return self._document(db.execute('SELECT * FROM documents WHERE user_id=? AND name=?', (self._owner(user_id), name)).fetchone())

    def put_document(self, name, document, expected, now, user_id=None, device_id=None):
        encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        user_id = self._owner(user_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM documents WHERE user_id=? AND name=?', (user_id, name)).fetchone()
            version = row['version'] if row else 0
            if expected is not None and version != expected:
                return False, self._document(row)
            values = (user_id, name, version+1, now, encoded, device_id)
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,name) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,document=excluded.document,updated_by=excluded.updated_by', values)
            db.execute('INSERT INTO document_history VALUES (?,?,?,?,?,?)', values)
            db.execute('DELETE FROM document_history WHERE user_id=? AND name=? AND version NOT IN (SELECT version FROM document_history WHERE user_id=? AND name=? ORDER BY version DESC LIMIT ?)', (user_id, name, user_id, name, self.history_limit))
        return True, {'version': version+1, 'updated_at': now, 'updated_by': device_id, 'document': document}

    def history(self, name, user_id, version=None):
        with self.connection() as db:
            if version is not None:
                return self._document(db.execute('SELECT * FROM document_history WHERE user_id=? AND name=? AND version=?', (user_id, name, version)).fetchone())
            return [self._document(r) for r in db.execute('SELECT * FROM document_history WHERE user_id=? AND name=? ORDER BY version DESC', (user_id, name))]

    def versions(self, user_id):
        with self.connection() as db:
            return {r['name']: {k:r[k] for k in ('version','updated_at','updated_by')} for r in db.execute('SELECT * FROM documents WHERE user_id=?', (user_id,))}

    def configure_bindings(self, bindings):
        if self.owner_id is None:
            if bindings:
                raise ValueError('source bindings require an explicit owner')
            return
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            revised=[]
            for binding in bindings:
                binding=dict(binding)
                configuration=binding.pop('_configuration_hash', None)
                fingerprint=self.digest(json.dumps({k:v for k,v in binding.items() if k!='version'}, sort_keys=True)+str(configuration))
                old=db.execute('SELECT * FROM binding_revisions WHERE user_id=? AND binding_id=?', (self.owner_id,binding['binding_id'])).fetchone()
                binding['version']=max(binding['version'],old['version']+int(old['fingerprint']!=fingerprint)) if old else binding['version']
                db.execute('INSERT OR REPLACE INTO binding_revisions VALUES (?,?,?,?)', (self.owner_id,binding['binding_id'],fingerprint,binding['version']))
                revised.append(binding)
            encoded=json.dumps(revised, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            fingerprint=self.digest(encoded)
            row = db.execute('SELECT * FROM source_bindings WHERE user_id=?', (self.owner_id,)).fetchone()
            if row and row['fingerprint'] == fingerprint:
                return
            version = row['version']+1 if row else 1
            db.execute('INSERT OR REPLACE INTO source_bindings VALUES (?,?,?,?)', (self.owner_id, version, fingerprint, encoded))

    def bindings(self, user_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM source_bindings WHERE user_id=?', (user_id,)).fetchone()
            return {'version': row['version'], 'items': json.loads(row['document'])} if row else {'version': 0, 'items': []}

    def source_snapshot(self, cache_key, document=None):
        """Disposable source metadata cache, never a business record or raw summary."""
        with self.connection() as db:
            if document is not None:
                db.execute('INSERT OR REPLACE INTO source_snapshots VALUES (?,?,?)', (self._owner(None), cache_key, json.dumps(document)))
            row=db.execute('SELECT document FROM source_snapshots WHERE user_id=? AND cache_key=?', (self._owner(None), cache_key)).fetchone()
            return json.loads(row['document']) if row else None

    def observe_attention(self, active, scopes, now, resolved=(), user_id=None):
        user_id = self._owner(user_id)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for row in db.execute('SELECT id FROM attention_state WHERE user_id=?', (user_id,)).fetchall():
                if (row['id'].split(':',1)[0] in scopes or row['id'] in resolved) and row['id'] not in active:
                    db.execute('DELETE FROM attention_state WHERE user_id=? AND id=?', (user_id, row['id']))
            for identifier, since in active.items():
                db.execute('INSERT OR IGNORE INTO attention_state(user_id,id,since) VALUES (?,?,?)', (user_id, identifier, since or now))
            return {r['id']:dict(r) for r in db.execute('SELECT * FROM attention_state WHERE user_id=?', (user_id,))}

    def handle_attention(self, identifier, until=None, user_id=None):
        with self.connection() as db:
            return db.execute('UPDATE attention_state SET dismissed=?,snooze_until=? WHERE user_id=? AND id=?', (int(until is None), until, self._owner(user_id), identifier)).rowcount > 0

    def save_login(self, kind, identifier, payload, expires, now):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM login_pending WHERE expires<=?', (now,))
            if db.execute('SELECT count(*) FROM login_pending').fetchone()[0]>=1000:
                return False
            db.execute('INSERT INTO login_pending VALUES (?,?,?,?)', (self.digest(identifier), kind, json.dumps(payload), expires))
        return True

    def consume_login(self, kind, identifier, now):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload,expires FROM login_pending WHERE id_hash=? AND kind=?', (self.digest(identifier), kind)).fetchone()
            db.execute('DELETE FROM login_pending WHERE id_hash=? OR expires<=?', (self.digest(identifier), now))
        return json.loads(row['payload']) if row and row['expires']>now else None

    def exchange_device(self, code, challenge, now, timestamp):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT payload,expires FROM login_pending WHERE id_hash=? AND kind='exchange'", (self.digest(code),)).fetchone()
            db.execute('DELETE FROM login_pending WHERE id_hash=? OR expires<=?', (self.digest(code), timestamp))
            if not row or row['expires']<=timestamp:
                return None
            payload = json.loads(row['payload'])
            if not payload.get('user_id') or not hmac.compare_digest(payload['challenge'], challenge):
                return None
            token, identifier = secrets.token_urlsafe(32), str(uuid4())
            db.execute('INSERT INTO devices(id,name,token_hash,created_at,last_seen,user_id) VALUES (?,?,?,?,?,?)', (identifier, payload['device_name'], self.digest(token), now, now, payload['user_id']))
        return {'device_id': identifier, 'token': token}
