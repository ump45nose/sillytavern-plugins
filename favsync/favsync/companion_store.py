"""Persistence and incremental public views for creator materials."""
import json
import time


def init_schema(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS companion_creators (
      creator_id TEXT PRIMARY KEY, name TEXT NOT NULL, last_scan REAL NOT NULL DEFAULT 0,
      cursor TEXT NOT NULL DEFAULT '', backfill_done INTEGER NOT NULL DEFAULT 0,
      scan_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending');
    CREATE TABLE IF NOT EXISTS companion_pending (
      note_id TEXT PRIMARY KEY, creator_id TEXT NOT NULL, published_at REAL NOT NULL,
      locator TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
    CREATE TABLE IF NOT EXISTS companion_changes (seq INTEGER PRIMARY KEY AUTOINCREMENT);
    CREATE TABLE IF NOT EXISTS companion_materials (
      note_id TEXT PRIMARY KEY, seq INTEGER NOT NULL UNIQUE, creator_id TEXT NOT NULL,
      published_at REAL NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
      ocr TEXT NOT NULL, replies TEXT NOT NULL, status TEXT NOT NULL, updated_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS companion_materials_seq ON companion_materials(seq);
    CREATE TABLE IF NOT EXISTS companion_ocr (
      cache_key TEXT PRIMARY KEY, text TEXT NOT NULL, scores TEXT NOT NULL,
      status TEXT NOT NULL, updated_at REAL NOT NULL);
    """)


def neighbour_links(db, creator_id):
    rows = db.execute("SELECT note_id FROM companion_materials WHERE creator_id=? "
                      "ORDER BY published_at,note_id", (creator_id,)).fetchall()
    ids = [row[0] for row in rows]
    return {key: (ids[i-1] if i else None, ids[i+1] if i+1 < len(ids) else None)
            for i, key in enumerate(ids)}


class CompanionStore:
    def __init__(self, db):
        self.db = db

    def authors(self, configured):
        with self.db:
            self.db.executemany("INSERT OR IGNORE INTO companion_creators(creator_id,name) VALUES(?,?)",
                                [(item["id"], item["name"]) for item in configured])
        ids = [item["id"] for item in configured]
        placeholders = ",".join("?" for _ in ids)
        return self.db.execute(f"SELECT * FROM companion_creators WHERE creator_id IN ({placeholders}) "
                               "ORDER BY last_scan,creator_id LIMIT 2", ids).fetchall()

    def start_scan(self, creator_id):
        with self.db:
            self.db.execute("UPDATE companion_creators SET last_scan=?,status='scanning' WHERE creator_id=?",
                            (time.time(), creator_id))

    def save_page(self, author, records, cursor, done, *, advance):
        # A refreshed locator must reach retries without resetting their state.
        with self.db:
            for note_id, published, locator, status in records:
                self.db.execute("INSERT INTO companion_pending VALUES(?,?,?,?,?) "
                                "ON CONFLICT(note_id) DO UPDATE SET locator=excluded.locator",
                                (note_id, author["creator_id"], published, json.dumps(locator), status))
            if advance:
                self.db.execute("UPDATE companion_creators SET cursor=?,backfill_done=? WHERE creator_id=?",
                                (cursor, int(done), author["creator_id"]))
            self.db.execute("UPDATE companion_creators SET scan_count=scan_count+1,status='cached' WHERE creator_id=?",
                            (author["creator_id"],))

    def next_note(self, author, cutoff, ttl):
        pending = self.db.execute("SELECT * FROM companion_pending WHERE creator_id=? AND status='pending' "
                                  "AND published_at>=? ORDER BY published_at DESC LIMIT 1",
                                  (author["creator_id"], cutoff)).fetchone()
        if author["scan_count"] % 3 == 0:
            latest = self.db.execute("SELECT p.* FROM companion_pending p JOIN companion_materials m USING(note_id) "
                                     "WHERE p.creator_id=? AND p.published_at>=? ORDER BY p.published_at DESC LIMIT 1",
                                     (author["creator_id"], cutoff)).fetchone()
            if latest and self.cached_note(latest["note_id"], ttl) is None and (
                    pending is None or pending["published_at"] <= latest["published_at"]):
                pending = latest
        return pending

    def _setting(self, key):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def cached_note(self, note_id, ttl):
        at = self._setting("companion_note_at:" + note_id)
        cached = self._setting("companion_note:" + note_id)
        return json.loads(cached) if cached and at and time.time()-float(at) < ttl else None

    def cache_note(self, note_id, note):
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO settings VALUES(?,?)", [
                ("companion_note:"+note_id, json.dumps(note, ensure_ascii=False)),
                ("companion_note_at:"+note_id, str(time.time()))])
            self.db.execute("DELETE FROM settings WHERE key=?", ("companion_replies:"+note_id,))

    def cached_comments(self, note_id):
        value = self._setting("companion_replies:" + note_id)
        return json.loads(value) if value is not None else None

    def retain_ready(self, note_id):
        ready = self.db.execute("SELECT 1 FROM companion_materials WHERE note_id=? AND status='ready'",
                                (note_id,)).fetchone()
        if ready:
            with self.db:
                self.db.execute("UPDATE companion_pending SET status='pending' WHERE note_id=?", (note_id,))
        return bool(ready)

    def _revision(self):
        seq = self.db.execute("INSERT INTO companion_changes DEFAULT VALUES").lastrowid
        # AUTOINCREMENT retains the high-water mark even after old rows are removed.
        self.db.execute("DELETE FROM companion_changes WHERE seq<>?", (seq,))
        return seq

    def save_material(self, pending, published, title, body, ocr, replies, status, comments):
        note_id, creator_id = pending["note_id"], pending["creator_id"]
        fields = (published, title, body, ocr, json.dumps(replies, ensure_ascii=False), status)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",
                            ("companion_replies:"+note_id,
                             json.dumps({"comments": comments.get("comments", [])}, ensure_ascii=False)))
            self.db.execute("UPDATE companion_pending SET status=? WHERE note_id=?",
                            ("pending" if status == "ocr_failed" else "cached", note_id))
            old = self.db.execute("SELECT published_at,title,body,ocr,replies,status FROM companion_materials "
                                  "WHERE note_id=?", (note_id,)).fetchone()
            if old is not None and tuple(old) == fields:
                return
            reordered = old is None or old[0] != published
            before = neighbour_links(self.db, creator_id) if reordered else {}
            self.db.execute("INSERT INTO companion_materials VALUES(?,?,?,?,?,?,?,?,?,?) "
                            "ON CONFLICT(note_id) DO UPDATE SET seq=excluded.seq,title=excluded.title,"
                            "published_at=excluded.published_at,body=excluded.body,ocr=excluded.ocr,"
                            "replies=excluded.replies,status=excluded.status,updated_at=excluded.updated_at",
                            (note_id, self._revision(), creator_id, *fields, time.time()))
            if reordered:
                for neighbour, links in neighbour_links(self.db, creator_id).items():
                    if neighbour != note_id and before.get(neighbour) != links:
                        self.db.execute("UPDATE companion_materials SET seq=?,updated_at=? WHERE note_id=?",
                                        (self._revision(), time.time(), neighbour))


def list_materials(db, cursor=0, limit=100):
    rows = db.execute("SELECT m.*,c.name FROM companion_materials m JOIN companion_creators c "
                      "USING(creator_id) WHERE seq>? ORDER BY seq LIMIT ?", (cursor, limit)).fetchall()
    output, links = [], {}
    for row in rows:
        if row["creator_id"] not in links:
            links[row["creator_id"]] = neighbour_links(db, row["creator_id"])
        previous, following = links[row["creator_id"]][row["note_id"]]
        output.append({"id": row["note_id"], "title": row["title"], "body": row["body"],
                       "ocr": row["ocr"], "replies": json.loads(row["replies"]), "status": row["status"],
                       "published_at": row["published_at"], "updated_at": row["updated_at"],
                       "source": {"platform": "xiaohongshu", "creator_id": row["creator_id"],
                                  "creator_name": row["name"],
                                  "url": "https://www.xiaohongshu.com/explore/" + row["note_id"]},
                       "previous_id": previous, "next_id": following})
    return {"materials": output, "next_cursor": str(rows[-1]["seq"] if rows else cursor),
            "has_more": bool(rows and db.execute("SELECT 1 FROM companion_materials WHERE seq>?",
                                                 (rows[-1]["seq"],)).fetchone()),
            "collection": [dict(r) for r in db.execute("SELECT creator_id,name,last_scan,status,backfill_done "
                                                       "FROM companion_creators ORDER BY creator_id")],
            "source_states": [dict(r) for r in db.execute("SELECT account,scan_status,error,last_scan "
                                                          "FROM sources WHERE name='xhs_creators'")]}
