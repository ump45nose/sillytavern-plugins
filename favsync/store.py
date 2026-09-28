from pathlib import Path
import json
import re
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
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(items)")}
        if "bundle_status" not in columns:
            self.db.execute("ALTER TABLE items ADD COLUMN bundle_status TEXT NOT NULL DEFAULT 'none'")
        if "error" not in columns:
            self.db.execute("ALTER TABLE items ADD COLUMN error TEXT")
        xhs_columns = {r[1] for r in self.db.execute("PRAGMA table_info(xhs_names)")}
        if "stem" not in xhs_columns:
            self.db.execute("ALTER TABLE xhs_names ADD COLUMN stem TEXT")
        # Old invalid Wallabag entries were retried every cycle. Keep their
        # locator so a later content change can requeue them.
        self.db.execute("""UPDATE items SET bundle_status='skipped_invalid',text_done=1
                           WHERE platform='wallabag' AND bundle_status='failed'
                           AND error='invalid_content'""")
        self.db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('markdown_v2_since',?)", (str(time.time()),))
        self.db.commit()

    def close(self):
        self.db.close()

    def record_execution(self, kind, started_at, success):
        with self.db:
            self.db.execute("INSERT INTO execution_history(kind,started_at,finished_at,result) VALUES(?,?,?,?)",
                            (kind, started_at, time.time(), "success" if success else "failed"))
            self.db.execute("DELETE FROM execution_history WHERE id NOT IN "
                            "(SELECT id FROM execution_history ORDER BY id DESC LIMIT 100)")

    def last_execution_finished(self, kind):
        row = self.db.execute("SELECT finished_at FROM execution_history WHERE kind=? ORDER BY id DESC LIMIT 1",
                              (kind,)).fetchone()
        return float(row[0]) if row else None

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

    def delete_setting(self, key):
        with self.db:
            self.db.execute("DELETE FROM settings WHERE key=?", (key,))

    def xhs_fuse(self, account):
        value = self.setting("xhs_fuse:" + account)
        return json.loads(value) if value else None

    def set_xhs_fuse(self, account, reason):
        self.setting("xhs_fuse:" + account, json.dumps({"reason": reason, "at": time.time()}))

    def clear_xhs_fuse(self, account):
        self.delete_setting("xhs_fuse:" + account)

    def seen_ids(self, source, account, item_ids):
        item_ids = list(dict.fromkeys(str(item_id) for item_id in item_ids if item_id))
        if not item_ids:
            return set()
        placeholders = ",".join("?" for _ in item_ids)
        rows = self.db.execute(
            f"SELECT item_id FROM seen WHERE source=? AND account=? AND item_id IN ({placeholders})",
            (source, account, *item_ids),
        )
        return {row[0] for row in rows}

    def xhs_detail(self, account, item_id, max_age):
        row = self.db.execute(
            "SELECT payload,updated_at FROM xhs_details WHERE account=? AND item_id=?",
            (account, item_id),
        ).fetchone()
        if not row or time.time() - row[1] > max_age:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None

    def save_xhs_detail(self, account, item_id, payload):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO xhs_details(account,item_id,payload,updated_at) VALUES(?,?,?,?)",
                (account, item_id, json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def delete_xhs_detail(self, account, item_id):
        with self.db:
            self.db.execute("DELETE FROM xhs_details WHERE account=? AND item_id=?", (account, item_id))

    def update_body(self, item, body):
        with self.db:
            self.db.execute("UPDATE items SET body=? WHERE platform=? AND account=? AND item_id=?",
                            (body, item["platform"], item["account"], item["item_id"]))

    def save_xhs_media(self, item, paths):
        with self.db:
            self.db.execute("DELETE FROM xhs_media WHERE account=? AND item_id=?",
                            (item["account"], item["item_id"]))
            self.db.executemany("INSERT INTO xhs_media(account,item_id,filename) VALUES(?,?,?)",
                                [(item["account"], item["item_id"], path.name) for path in paths])

    def xhs_media_files(self, item, root):
        names = [row[0] for row in self.db.execute(
            "SELECT filename FROM xhs_media WHERE account=? AND item_id=? ORDER BY filename",
            (item["account"], item["item_id"]))]
        if not names:
            row = self.db.execute("SELECT stem FROM xhs_names WHERE account=? AND item_id=?",
                                  (item["account"], item["item_id"])).fetchone()
            if row and row[0] and Path(root).is_dir():
                pattern = re.compile(re.escape(row[0]) + r"(?:_\d{3})?\.(?:jpg|jpeg|png|webp|heic|mp4|mov)$", re.I)
                names = [path.name for path in Path(root).iterdir() if path.is_file() and pattern.fullmatch(path.name)]
                if names:
                    self.save_xhs_media(item, sorted(Path(root) / name for name in names))
        return [Path(root) / name for name in names]

    def xhs_name_stem(self, item):
        row = self.db.execute("SELECT stem FROM xhs_names WHERE account=? AND item_id=?",
                              (item["account"], item["item_id"])).fetchone()
        return row[0] if row else None

    def markdown_pending(self, source, account):
        cutoff = float(self.setting("markdown_v2_since") or 0)
        platform = SOURCE_PLATFORM[source]
        return self.db.execute("""SELECT i.* FROM seen s JOIN items i
          ON i.platform=? AND i.account=s.account AND i.item_id=s.item_id
          LEFT JOIN markdown_exports m ON m.source=s.source AND m.account=s.account AND m.item_id=s.item_id
          WHERE s.source=? AND s.account=? AND s.first_seen_at>=? AND s.baseline=0 AND m.item_id IS NULL
          ORDER BY s.first_seen_at,i.item_id""", (platform, source, account, cutoff)).fetchall()

    def is_legacy_item(self, source, account, item_id):
        row = self.db.execute("SELECT first_seen_at FROM seen WHERE source=? AND account=? AND item_id=?",
                              (source, account, item_id)).fetchone()
        return bool(row and row[0] < float(self.setting("markdown_v2_since") or 0))

    def markdown_result(self, source, account, item_id, filename, status):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO markdown_exports VALUES(?,?,?,?,?)",
                            (source, account, item_id, filename, status))

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
                if baseline or (not fresh and (source == "x_likes" or source.startswith("pixiv_"))):
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
                    if r.get("text"):
                        self.db.execute("UPDATE items SET body=? WHERE platform=? AND account=? AND item_id=? AND body=''",
                                        (r["text"], platform, account, r["id"]))
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
        """Commit a complete page walk; retry invalid entries only after repair."""
        now = time.time()
        with self.db:
            for record in records:
                item_id = record["id"]
                self.db.execute("INSERT OR IGNORE INTO seen VALUES(?,?,?,?,0)",
                                (source, account, item_id, now))
                locator = json.dumps(record["locator"], ensure_ascii=False)
                invalid = bool(record["locator"].get("invalid_content"))
                item = self.db.execute(
                    "SELECT bundle_status,error,text_done FROM items WHERE platform='wallabag' AND account=? AND item_id=?",
                    (account, item_id)).fetchone()
                if item is None:
                    self.db.execute("""INSERT INTO items(platform,account,item_id,body,locator,
                                      bundle_status,error,text_done) VALUES('wallabag',?,?,?,?,?,?,?)""",
                                    (account, item_id, "", locator,
                                     "skipped_invalid" if invalid else "pending",
                                     "invalid_content" if invalid else None, int(invalid)))
                    continue
                exported = self.db.execute(
                    "SELECT fingerprint FROM wallabag_exports WHERE account=? AND entry_id=?",
                    (account, item_id)).fetchone()
                changed = exported is None or exported[0] != record["locator"]["fingerprint"]
                if invalid:
                    bundle_status, error, text_done = "skipped_invalid", "invalid_content", 1
                elif changed or item[0] == "skipped_invalid":
                    bundle_status, error, text_done = "pending", None, 0
                else:
                    bundle_status, error, text_done = item
                self.db.execute("""UPDATE items SET locator=?,bundle_status=?,error=?,text_done=?
                                  WHERE platform='wallabag' AND account=? AND item_id=?""",
                                (locator, bundle_status, error, text_done, account, item_id))
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
        status = ("done" if not error else "skipped_invalid"
                  if item["platform"] == "wallabag" and error == "invalid_content" else
                  "paused_low_disk" if error == "paused_low_disk" else "failed")
        with self.db:
            self.db.execute("UPDATE items SET bundle_status=?,error=?,text_done=? WHERE platform=? AND account=? AND item_id=?",
                            (status, error, 1 if status in ("done", "skipped_invalid") else 0,
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
            "bundle_errors": [dict(r) for r in self.db.execute("SELECT platform,account,bundle_status,error,count(*) AS count FROM items WHERE error IS NOT NULL GROUP BY platform,account,bundle_status,error")],
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
            "xhs_fuses": {row[0].split(":", 1)[1]: json.loads(row[1])
                           for row in self.db.execute("SELECT key,value FROM settings WHERE key LIKE 'xhs_fuse:%'")},
            "xhs_observations": [json.loads(row[0]) for row in self.db.execute(
                "SELECT value FROM settings WHERE key LIKE 'xhs_observation:%' ORDER BY key")],
            "markdown_exports": [dict(row) for row in self.db.execute(
                "SELECT source,status,count(*) AS count FROM markdown_exports GROUP BY source,status")],
        }
