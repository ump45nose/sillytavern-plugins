"""Connection creation and one-time, versioned migrations of the shared SQLite."""
from contextlib import closing
from pathlib import Path
import sqlite3
import time

from .common import SyncError, process_lock
from .film_store import init_schema

SCHEMA_VERSION = 3


def connect(state, *, readonly=False):
    path = Path(state).resolve() / "state.sqlite3"
    if not path.is_file():
        raise SyncError("state_not_initialized")
    db = sqlite3.connect(path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                         uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def migrate(state):
    """Run only at writer application startup, never when reading status."""
    Path(state).mkdir(parents=True, exist_ok=True)
    with process_lock(state, name="schema", blocking=True):
        with closing(sqlite3.connect(Path(state) / "state.sqlite3", timeout=30)) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise SyncError("schema_newer_than_application")
            if version == SCHEMA_VERSION:
                return
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            _upgrade(db)


def _upgrade(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sources (
      name TEXT NOT NULL, account TEXT NOT NULL, baseline_at REAL,
      cursor INTEGER NOT NULL DEFAULT 0, start_date TEXT NOT NULL DEFAULT '',
      scan_status TEXT NOT NULL DEFAULT 'idle', last_scan REAL,
      error TEXT,
      PRIMARY KEY(name, account));
    CREATE TABLE IF NOT EXISTS seen (
      source TEXT NOT NULL, account TEXT NOT NULL, item_id TEXT NOT NULL,
      first_seen_at REAL NOT NULL, baseline INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(source, account, item_id));
    CREATE TABLE IF NOT EXISTS items (
      platform TEXT NOT NULL, account TEXT NOT NULL, item_id TEXT NOT NULL,
      body TEXT NOT NULL, locator TEXT NOT NULL, text_done INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(platform, account, item_id));
    CREATE TABLE IF NOT EXISTS assets (
      platform TEXT NOT NULL, account TEXT NOT NULL, item_id TEXT NOT NULL,
      number INTEGER NOT NULL, filename TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0, error TEXT, size INTEGER,
      PRIMARY KEY(platform, account, item_id, number),
      FOREIGN KEY(platform,account,item_id) REFERENCES items(platform,account,item_id));
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS xhs_names (
      account TEXT NOT NULL, author TEXT NOT NULL, published TEXT NOT NULL,
      item_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
      PRIMARY KEY(account,item_id), UNIQUE(account,author,published,ordinal));
    CREATE TABLE IF NOT EXISTS eh_names (
      account TEXT NOT NULL, item_id TEXT NOT NULL, relative_path TEXT NOT NULL,
      PRIMARY KEY(account,item_id), UNIQUE(account,relative_path));
    CREATE TABLE IF NOT EXISTS execution_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      kind TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL NOT NULL,
      result TEXT NOT NULL CHECK(result IN ('success','failed')));
    CREATE TABLE IF NOT EXISTS pixiv_names (
      account TEXT NOT NULL, item_id TEXT NOT NULL, stem TEXT NOT NULL,
      PRIMARY KEY(account,item_id), UNIQUE(account,stem));
    CREATE TABLE IF NOT EXISTS wallabag_exports (
      account TEXT NOT NULL, entry_id TEXT NOT NULL, fingerprint TEXT,
      filename TEXT NOT NULL, attachment_status TEXT,
      PRIMARY KEY(account,entry_id), UNIQUE(account,filename));
    CREATE TABLE IF NOT EXISTS xhs_details (
      account TEXT NOT NULL, item_id TEXT NOT NULL, payload TEXT NOT NULL,
      updated_at REAL NOT NULL,
      PRIMARY KEY(account,item_id));
    CREATE TABLE IF NOT EXISTS xhs_media (
      account TEXT NOT NULL, item_id TEXT NOT NULL, filename TEXT NOT NULL,
      PRIMARY KEY(account,item_id,filename));
    CREATE TABLE IF NOT EXISTS markdown_exports (
      source TEXT NOT NULL, account TEXT NOT NULL, item_id TEXT NOT NULL,
      filename TEXT NOT NULL, status TEXT NOT NULL,
      PRIMARY KEY(source,account,item_id));
    """)
    init_schema(db)
    from .companion_materials import init_schema as init_companion_schema
    init_companion_schema(db)
    columns = {r[1] for r in db.execute("PRAGMA table_info(items)")}
    if "bundle_status" not in columns:
        db.execute("ALTER TABLE items ADD COLUMN bundle_status TEXT NOT NULL DEFAULT 'none'")
    if "error" not in columns:
        db.execute("ALTER TABLE items ADD COLUMN error TEXT")
    xhs_columns = {r[1] for r in db.execute("PRAGMA table_info(xhs_names)")}
    if "stem" not in xhs_columns:
        db.execute("ALTER TABLE xhs_names ADD COLUMN stem TEXT")
    # Old invalid Wallabag entries were retried every cycle. Keep their
    # locator so a later content change can requeue them.
    db.execute("""UPDATE items SET bundle_status='skipped_invalid',text_done=1
                       WHERE platform='wallabag' AND bundle_status='failed'
                       AND error='invalid_content'""")
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('markdown_v2_since',?)", (str(time.time()),))
    source_columns = {r[1] for r in db.execute("PRAGMA table_info(sources)")}
    if "scan_reason" not in source_columns:
        db.execute("ALTER TABLE sources ADD COLUMN scan_reason TEXT")
    export_columns = {r[1] for r in db.execute("PRAGMA table_info(wallabag_exports)")}
    if "attachment_reason" not in export_columns:
        db.execute("ALTER TABLE wallabag_exports ADD COLUMN attachment_reason TEXT")
    # Deleted X media and missing images in a valid text EPUB are terminal
    # skips. Preserve errors/attempt counts and local files for inspection.
    db.execute("""UPDATE assets SET status='skipped_unavailable'
                  WHERE platform='x' AND status='failed' AND error='content_unavailable'""")
    db.execute("""UPDATE items SET text_done=1 WHERE platform='x'
                  AND EXISTS(SELECT 1 FROM assets a WHERE a.platform=items.platform
                    AND a.account=items.account AND a.item_id=items.item_id)
                  AND NOT EXISTS(SELECT 1 FROM assets a WHERE a.platform=items.platform
                    AND a.account=items.account AND a.item_id=items.item_id
                    AND a.status NOT IN ('done','skipped_unavailable'))""")
    db.execute("""UPDATE wallabag_exports SET attachment_status='skipped_unavailable',
                  attachment_reason='images_not_embedded' WHERE attachment_status='incomplete'""")
    db.execute("PRAGMA user_version=3")
    db.commit()
