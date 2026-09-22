from pathlib import Path
import json
import sqlite3
import time
from .config import SOURCE_PLATFORM


class Store:
    def __init__(self, state):
        Path(state).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(Path(state) / "state.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS sources (
          name TEXT NOT NULL, account TEXT NOT NULL, baseline_at REAL,
          cursor INTEGER NOT NULL DEFAULT 0, start_date TEXT NOT NULL DEFAULT '',
          scan_status TEXT NOT NULL DEFAULT 'idle', last_scan REAL,
          error TEXT, blocked_cookie TEXT,
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
        """)
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(items)")}
        if "bundle_status" not in columns:
            self.db.execute("ALTER TABLE items ADD COLUMN bundle_status TEXT NOT NULL DEFAULT 'none'")
        if "error" not in columns:
            self.db.execute("ALTER TABLE items ADD COLUMN error TEXT")
        xhs_columns = {r[1] for r in self.db.execute("PRAGMA table_info(xhs_names)")}
        if "stem" not in xhs_columns:
            self.db.execute("ALTER TABLE xhs_names ADD COLUMN stem TEXT")
        self.db.commit()

    def close(self):
        self.db.close()

    def record_execution(self, kind, started_at, success):
        with self.db:
            self.db.execute("INSERT INTO execution_history(kind,started_at,finished_at,result) VALUES(?,?,?,?)",
                            (kind, started_at, time.time(), "success" if success else "failed"))
            self.db.execute("DELETE FROM execution_history WHERE id NOT IN "
                            "(SELECT id FROM execution_history ORDER BY id DESC LIMIT 100)")

    def source(self, name, account):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO sources(name,account) VALUES(?,?)", (name, account))
        return dict(self.db.execute("SELECT * FROM sources WHERE name=? AND account=?", (name, account)).fetchone())

    def update(self, name, account, **values):
        allowed = {"baseline_at", "cursor", "start_date", "scan_status", "last_scan", "error", "blocked_cookie"}
        assert values.keys() <= allowed
        with self.db:
            self.db.execute("UPDATE sources SET " + ",".join(k + "=?" for k in values) + " WHERE name=? AND account=?", (*values.values(), name, account))

    def setting(self, key, value=None):
        if value is not None:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value))
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def ingest(self, source, account, records, baseline=False, cursor=None, start_date=""):
        """One transaction: complete baseline OR seen + durable queue + scan cursor."""
        now = time.time()
        platform = SOURCE_PLATFORM.get(source)
        if not platform:
            raise ValueError("unknown source")
        with self.db:
            for r in records:
                fresh = self.db.execute(
                    "INSERT OR IGNORE INTO seen VALUES(?,?,?,?,?)",
                    (source, account, r["id"], now, int(baseline))).rowcount
                if baseline or (source == "x_likes" and not fresh):
                    continue
                bundle = "pending" if r.get("bundle") else "none"
                new_item = self.db.execute("INSERT OR IGNORE INTO items(platform,account,item_id,body,locator,bundle_status) VALUES(?,?,?,?,?,?)",
                                          (platform, account, r["id"], r.get("text", ""), json.dumps(r["locator"]), bundle)).rowcount
                if not new_item and r['locator'].get('naming'):
                    row = self.db.execute('SELECT locator FROM items WHERE platform=? AND account=? AND item_id=?',
                                          (platform, account, r['id'])).fetchone()
                    old = json.loads(row[0])
                    # Refresh signed XHS locators while preserving the allocated name.
                    naming = old.get('naming') or r['locator'].get('naming')
                    fresh_locator = dict(r['locator'])
                    for frozen in ('author', 'published'):
                        if old.get(frozen):
                            fresh_locator[frozen] = old[frozen]
                    if naming:
                        fresh_locator['naming'] = naming
                    self.db.execute('UPDATE items SET locator=? WHERE platform=? AND account=? AND item_id=?',
                                    (json.dumps(fresh_locator), platform, account, r['id']))
                for number, filename in (r["assets"] if new_item else []):
                    self.db.execute("INSERT OR IGNORE INTO assets(platform,account,item_id,number,filename) VALUES(?,?,?,?,?)",
                                    (platform, account, r["id"], number, filename))
            self.db.execute("UPDATE sources SET scan_status='complete',error=NULL,last_scan=?,blocked_cookie=NULL,start_date=? WHERE name=? AND account=?",
                            (now, start_date, source, account))
            if baseline:
                self.db.execute("UPDATE sources SET baseline_at=? WHERE name=? AND account=?", (now, source, account))
            if cursor is not None:
                self.db.execute("UPDATE sources SET cursor=? WHERE name=? AND account=?", (cursor, source, account))

    def ingest_wallabag(self, source, account, records):
        """Commit a complete Wallabag page walk while preserving failed exports."""
        now = time.time()
        with self.db:
            for record in records:
                item_id = record["id"]
                self.db.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?,?,0)",
                                (source, account, item_id, now))
                locator = json.dumps(record["locator"], ensure_ascii=False)
                item = self.db.execute(
                    "SELECT bundle_status,error,text_done FROM items WHERE platform='wallabag' AND account=? AND item_id=?",
                    (account, item_id)).fetchone()
                if item is None:
                    self.db.execute("""INSERT INTO items(platform,account,item_id,body,locator,bundle_status)
                                      VALUES('wallabag',?,?,?,?, 'pending')""",
                                    (account, item_id, "", locator))
                    continue
                exported = self.db.execute(
                    "SELECT fingerprint FROM wallabag_exports WHERE account=? AND entry_id=?",
                    (account, item_id)).fetchone()
                changed = exported is None or exported[0] != record["locator"]["fingerprint"]
                self.db.execute("""UPDATE items SET locator=?,bundle_status=?,error=?,text_done=?
                                  WHERE platform='wallabag' AND account=? AND item_id=?""",
                                (locator, "pending" if changed else item[0], None if changed else item[1],
                                 0 if changed else item[2], account, item_id))
            self.db.execute("""UPDATE sources SET scan_status='complete',error=NULL,last_scan=?,blocked_cookie=NULL
                              WHERE name=? AND account=?""", (now, source, account))

    def pending(self, source, account):
        platform = SOURCE_PLATFORM.get(source)
        return self.db.execute("""SELECT DISTINCT i.* FROM items i JOIN seen s
          ON s.account=i.account AND s.item_id=i.item_id
          WHERE s.source=? AND i.platform=? AND i.account=? AND s.baseline=0
          AND (i.bundle_status IN ('pending','failed','paused_low_disk') OR i.text_done=0 OR EXISTS(SELECT 1 FROM assets a WHERE
            a.platform=i.platform AND a.account=i.account AND a.item_id=i.item_id AND a.status!='done'))
          ORDER BY i.item_id""", (source, platform, account)).fetchall()

    def assets(self, item):
        return self.db.execute("SELECT * FROM assets WHERE platform=? AND account=? AND item_id=? ORDER BY number",
                               (item["platform"], item["account"], item["item_id"])).fetchall()

    def bundle_result(self, item, error=None):
        status = "done" if not error else ("paused_low_disk" if error == "paused_low_disk" else "failed")
        with self.db:
            self.db.execute("UPDATE items SET bundle_status=?,error=?,text_done=? WHERE platform=? AND account=? AND item_id=?",
                            (status, error, 0 if error else 1,
                             item["platform"], item["account"], item["item_id"]))

    def xhs_ordinal(self, account, author, published, item_id):
        row = self.db.execute("SELECT ordinal FROM xhs_names WHERE account=? AND item_id=?", (account,item_id)).fetchone()
        if row:
            return row[0]
        with self.db:
            ordinal = self.db.execute("SELECT coalesce(max(ordinal),0)+1 FROM xhs_names WHERE account=? AND author=? AND published=?",
                                      (account,author,published)).fetchone()[0]
            self.db.execute("INSERT INTO xhs_names(account,author,published,item_id,ordinal) VALUES(?,?,?,?,?)",
                            (account,author,published,item_id,ordinal))
        return ordinal

    def xhs_stem(self, account, author, published, item_id, proposed, output_dir):
        row = self.db.execute("SELECT stem FROM xhs_names WHERE account=? AND item_id=?", (account,item_id)).fetchone()
        if row and row[0]:
            return row[0]
        collision = self.db.execute("SELECT 1 FROM xhs_names WHERE account=? AND item_id!=? AND stem=?",
                                    (account,item_id,proposed)).fetchone()
        if not collision:
            collision = any(Path(output_dir).glob(proposed + ".*")) or any(Path(output_dir).glob(proposed + "_???.*"))
        stem = proposed if not collision else proposed + "_" + item_id
        with self.db:
            self.db.execute("UPDATE xhs_names SET stem=? WHERE account=? AND item_id=?", (stem,account,item_id))
        return stem

    def pixiv_stem(self, account, item_id, proposed):
        row = self.db.execute("SELECT stem FROM pixiv_names WHERE account=? AND item_id=?",
                              (account, item_id)).fetchone()
        if row:
            return row[0]
        collision = self.db.execute("SELECT 1 FROM pixiv_names WHERE account=? AND stem=?",
                                    (account, proposed)).fetchone()
        stem = proposed if not collision else proposed + "_" + item_id.replace(":", "-")
        with self.db:
            self.db.execute("INSERT INTO pixiv_names VALUES(?,?,?)", (account, item_id, stem))
        return stem

    def wallabag_path(self, account, entry_id, proposed):
        row = self.db.execute("SELECT filename FROM wallabag_exports WHERE account=? AND entry_id=?",
                              (account, entry_id)).fetchone()
        if row:
            return row[0]
        collision = self.db.execute("SELECT 1 FROM wallabag_exports WHERE account=? AND filename=?",
                                    (account, proposed)).fetchone()
        filename = proposed if not collision else f"{Path(proposed).stem}_{entry_id}.epub"
        with self.db:
            self.db.execute("INSERT INTO wallabag_exports(account,entry_id,filename) VALUES(?,?,?)",
                            (account, entry_id, filename))
        return filename

    def wallabag_export_result(self, account, entry_id, fingerprint, attachment_status):
        with self.db:
            self.db.execute("""UPDATE wallabag_exports SET fingerprint=?,attachment_status=?
                              WHERE account=? AND entry_id=?""",
                            (fingerprint, attachment_status, account, entry_id))

    def eh_path(self, account, item_id, artist, title, output_dir):
        row = self.db.execute("SELECT relative_path FROM eh_names WHERE account=? AND item_id=?",
                              (account,item_id)).fetchone()
        if row:
            return Path(output_dir) / row[0]
        relative = str(Path(artist) / f"{title}.zip")
        collision = self.db.execute("SELECT 1 FROM eh_names WHERE account=? AND relative_path=?",
                                    (account,relative)).fetchone()
        if collision or (Path(output_dir) / relative).exists():
            relative = str(Path(artist) / f"{title}_[{item_id}].zip")
        with self.db:
            self.db.execute("INSERT INTO eh_names VALUES(?,?,?)", (account,item_id,relative))
        return Path(output_dir) / relative

    def asset_result(self, asset, error=None, size=None):
        with self.db:
            self.db.execute("UPDATE assets SET status=?,attempts=attempts+1,error=?,size=? WHERE platform=? AND account=? AND item_id=? AND number=?",
                            ("failed" if error else "done", error, size, asset["platform"], asset["account"], asset["item_id"], asset["number"]))

    def text_done(self, item):
        with self.db:
            self.db.execute("UPDATE items SET text_done=1 WHERE platform=? AND account=? AND item_id=?",
                            (item["platform"], item["account"], item["item_id"]))

    def status(self):
        return {
            "sources": [dict(r) for r in self.db.execute("SELECT name,account,baseline_at,cursor,start_date,scan_status,last_scan,error FROM sources")],
            "assets": [dict(r) for r in self.db.execute("SELECT platform,account,status,count(*) AS count FROM assets GROUP BY platform,account,status")],
            "download_errors": [dict(r) for r in self.db.execute("SELECT platform,account,error,count(*) AS count FROM assets WHERE error IS NOT NULL GROUP BY platform,account,error")],
            "bundles": [dict(r) for r in self.db.execute("SELECT platform,account,bundle_status,count(*) AS count FROM items GROUP BY platform,account,bundle_status")],
            "bundle_errors": [dict(r) for r in self.db.execute("SELECT platform,account,error,count(*) AS count FROM items WHERE error IS NOT NULL GROUP BY platform,account,error")],
            "text_pending": self.db.execute("SELECT count(*) FROM items WHERE text_done=0").fetchone()[0],
            "storage": {"paused_low_disk": self.setting("low_disk_paused") == "1",
                        "free_bytes": int(self.setting("disk_free_bytes") or 0)},
            "cookiecloud": self.setting("cookiecloud_status"),
            "cookiecloud_last_success": self.setting("cookiecloud_last_success"),
            "cookiecloud_platforms": {name: self.setting("cookiecloud_status:" + name)
                                      for name in ("x", "xhs", "eh")
                                      if self.setting("cookiecloud_status:" + name) is not None},
            "execution_history": [dict(r) for r in self.db.execute(
                "SELECT kind,started_at,finished_at,result FROM execution_history ORDER BY id DESC LIMIT 20")],
            "wallabag_exports": [dict(r) for r in self.db.execute(
                "SELECT attachment_status,count(*) AS count FROM wallabag_exports GROUP BY attachment_status")],
        }
