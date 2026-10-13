"""Budgeted creator text collection. Private locators never leave this module."""
from datetime import datetime, timezone
import json
import logging
import re
import time

from .common import SyncError

CREATORS = (
    ("629340f50000000021022155", "光芒"),
    ("5cd825820000000017005523", "小羊安妮"),
    ("67427b07000000001d02c163", "小黄油卷卷"),
    ("60e1b5340000000001002188", "不吃了佳"),
    ("5ff97f2e000000000100bdb3", "集市漫过街"),
    ("5d34856b0000000011029136", "往头上钉"),
    ("60febf200000000001000c01", "晓濛的日记本"),
    ("60f946c8000000000101480a", "二十五度秋"),
)


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


def meaningful(text):
    return re.sub(r"#[^\s#]+(?:\[话题\])?#?", "", text or "").strip()


def stamp(note):
    value = float(note.get("time") or note.get("publish_time") or 0)
    return value / 1000 if value > 100000000000 else value


def request(adapter, *args):
    from .adapters_ext import _json_command
    adapter._pace()
    result = _json_command([adapter.cfg["xhs"]["cli_binary"], *args, "--json"],
                           120, env=adapter._env())
    # Use the adapter's existing structured risk classifier.
    adapter.check_response(result)
    return result.get("data", result)


def sync_creators(adapter, store, section):
    db = store.db
    configured = section.get("creators", [{"id": i, "name": n} for i, n in CREATORS])
    for item in configured:
        if not re.fullmatch(r"[0-9a-f]{24}", item["id"]):
            raise SyncError("invalid_export")
        db.execute("INSERT OR IGNORE INTO companion_creators(creator_id,name) VALUES(?,?)",
                   (item["id"], item["name"]))
    db.commit()
    ids = [item["id"] for item in configured]
    placeholders = ",".join("?" for _ in ids)
    authors = db.execute(f"SELECT * FROM companion_creators WHERE creator_id IN ({placeholders}) "
                         "ORDER BY last_scan,creator_id LIMIT 2", ids).fetchall()
    cutoff = time.time() - 90 * 86400
    remaining = min(2, adapter._detail_remaining)
    for author in authors:
        author_id = author["creator_id"]
        # Alternate head refresh and incremental archive pages; newest pending wins.
        cursor = author["cursor"] if author["scan_count"] % 2 and not author["backfill_done"] else ""
        db.execute("UPDATE companion_creators SET last_scan=?,status='scanning' WHERE creator_id=?",
                   (time.time(), author_id)); db.commit()
        page = request(adapter, "user-posts", author_id, "--cursor", cursor)
        notes = page.get("notes") or page.get("items") or []
        adapter.observe("scan_pages")
        for note in notes:
            note_id = str(note.get("note_id") or note.get("id") or "")
            published = stamp(note)
            if not re.fullmatch(r"[0-9a-f]{24}", note_id) or published < cutoff:
                continue
            status = "skipped_video" if note.get("type") == "video" else "pending"
            locator = {"token": note.get("xsec_token", ""), "title": note.get("display_title", "")}
            db.execute("INSERT OR IGNORE INTO companion_pending VALUES(?,?,?,?,?)",
                       (note_id, author_id, published, json.dumps(locator), status))
        next_cursor = str(page.get("cursor") or "")
        done = not page.get("has_more", False) or bool(notes and all(stamp(n) < cutoff for n in notes))
        if cursor or not author["cursor"]:
            db.execute("UPDATE companion_creators SET cursor=?,backfill_done=? WHERE creator_id=?",
                       (next_cursor, int(done), author_id))
        db.execute("UPDATE companion_creators SET scan_count=scan_count+1,status='cached' WHERE creator_id=?",
                   (author_id,)); db.commit()
        # One detail per author, two reserved slots per cycle, shared with favorites/likes.
        pending = db.execute("SELECT * FROM companion_pending WHERE creator_id=? AND status='pending' "
                             "AND published_at>=? ORDER BY published_at DESC LIMIT 1", (author_id, cutoff)).fetchone()
        # Periodically refresh the most recent cached post/replies with the
        # existing detail TTL. Other turns continue archive work, avoiding a
        # permanently refreshed head starving the 90-day backfill.
        if author["scan_count"] % 3 == 0:
            latest = db.execute("SELECT p.* FROM companion_pending p JOIN companion_materials m USING(note_id) "
                                "WHERE p.creator_id=? AND p.published_at>=? ORDER BY p.published_at DESC LIMIT 1",
                                (author_id, cutoff)).fetchone()
            if latest:
                at = db.execute("SELECT value FROM settings WHERE key=?", ("companion_note_at:"+latest["note_id"],)).fetchone()
                if (time.time()-float(at[0] if at else 0) > adapter.cfg["xhs"]["detail_cache_ttl_seconds"]
                        and (pending is None or pending["published_at"] <= latest["published_at"])):
                    pending = latest
        if pending is not None and remaining:
            remaining -= 1
            locator = json.loads(pending["locator"])
            cached = db.execute("SELECT value FROM settings WHERE key=?", ("companion_note:"+pending["note_id"],)).fetchone()
            cached_at = db.execute("SELECT value FROM settings WHERE key=?", ("companion_note_at:"+pending["note_id"],)).fetchone()
            if cached and cached_at and time.time()-float(cached_at[0]) < adapter.cfg["xhs"]["detail_cache_ttl_seconds"]:
                note = json.loads(cached[0])
            else:
                adapter._detail_remaining -= 1
                adapter.observe("detail_requests")
                data = request(adapter, "read", pending["note_id"], "--xsec-token", locator["token"])
                note = data.get("note") or data.get("note_card") or data
                if "items" in note:
                    note = note["items"][0].get("note_card", note["items"][0])
                db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",
                           ("companion_note:"+pending["note_id"], json.dumps(note, ensure_ascii=False)))
                db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",
                           ("companion_note_at:"+pending["note_id"], str(time.time())))
                db.execute("DELETE FROM settings WHERE key=?", ("companion_replies:"+pending["note_id"],))
                db.commit()
            save_note(adapter, db, pending, note, locator)
    store.update("xhs_creators", section["account"], scan_status="cached", error=None, last_scan=time.time())


def save_note(adapter, db, pending, note, locator):
    from .companion_ocr import image_text
    body = str(note.get("desc") or note.get("description") or note.get("content") or "")
    title = str(note.get("title") or locator.get("title") or "")
    ocr, status = [], "ready"
    if len(meaningful(body)) < 80:
        images = note.get("image_list") or note.get("images") or []
        for item in images[:2]:
            url = item.get("url_default") or item.get("url") or ""
            if not url:
                info = item.get("info_list") or []
                url = next((v.get("url", "") for v in info if v.get("image_scene") == "WB_DFT"), "")
            try:
                text = image_text(db, url)
                if text:
                    ocr.append(text)
            except Exception as exc:
                status = "ocr_failed"
                logging.getLogger("favsync").warning("companion OCR: %s (cached body retained)", type(exc).__name__)
        if not ocr and len(meaningful(body)) < 40:
            status = "insufficient_text" if status == "ready" else status
    if status == "ocr_failed" and db.execute(
            "SELECT 1 FROM companion_materials WHERE note_id=? AND status='ready'",
            (pending["note_id"],)).fetchone():
        # A failed refresh must not replace a previously usable public cache.
        # Keep the locator/raw response so the next budgeted turn can retry.
        db.execute("UPDATE companion_pending SET status='pending' WHERE note_id=?",
                   (pending["note_id"],))
        db.commit()
        return
    replies = []
    cached_replies = db.execute("SELECT value FROM settings WHERE key=?", ("companion_replies:"+pending["note_id"],)).fetchone()
    comments = json.loads(cached_replies[0]) if cached_replies else request(adapter, "comments", pending["note_id"], "--xsec-token", locator["token"])
    for comment in (comments.get("comments") or [])[:30]:
        candidates = [comment, *(comment.get("sub_comments") or [])[:5]]
        for reply in candidates:
            user = reply.get("user_info") or reply.get("user") or {}
            if str(user.get("user_id") or user.get("id")) == pending["creator_id"]:
                text = str(reply.get("content") or "")[:600]
                if text and len(replies) < 5:
                    replies.append(text)
    db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",
               ("companion_replies:"+pending["note_id"], json.dumps({"comments": comments.get("comments", [])}, ensure_ascii=False)))
    seq = db.execute("INSERT INTO companion_changes DEFAULT VALUES").lastrowid
    db.execute("INSERT INTO companion_materials VALUES(?,?,?,?,?,?,?,?,?,?) "
               "ON CONFLICT(note_id) DO UPDATE SET seq=excluded.seq,title=excluded.title,"
               "published_at=excluded.published_at,body=excluded.body,ocr=excluded.ocr,"
               "replies=excluded.replies,status=excluded.status,updated_at=excluded.updated_at",
               (pending["note_id"], seq, pending["creator_id"], stamp(note) or pending["published_at"], title,
                body, "\n".join(ocr), json.dumps(replies, ensure_ascii=False), status, time.time()))
    db.execute("UPDATE companion_pending SET status=? WHERE note_id=?",
               ("pending" if status == "ocr_failed" else "cached", pending["note_id"],))
    # Neighbour links are part of the incremental cache contract: publish their
    # changed revisions too, without fetching their notes again.
    for comparison, ordering in (("<", "DESC"), (">", "ASC")):
        neighbour = db.execute(f"SELECT note_id FROM companion_materials WHERE creator_id=? "
                               f"AND published_at{comparison}? ORDER BY published_at {ordering} LIMIT 1",
                               (pending["creator_id"], stamp(note) or pending["published_at"])).fetchone()
        if neighbour:
            revision = db.execute("INSERT INTO companion_changes DEFAULT VALUES").lastrowid
            db.execute("UPDATE companion_materials SET seq=?,updated_at=? WHERE note_id=?",
                       (revision, time.time(), neighbour[0]))
    db.commit()


def list_materials(db, cursor=0, limit=100):
    rows = db.execute("SELECT m.*,c.name FROM companion_materials m JOIN companion_creators c "
                      "USING(creator_id) WHERE seq>? ORDER BY seq LIMIT ?", (cursor, limit)).fetchall()
    output = []
    for row in rows:
        previous = db.execute("SELECT note_id FROM companion_materials WHERE creator_id=? "
                              "AND published_at<? ORDER BY published_at DESC LIMIT 1",
                              (row["creator_id"], row["published_at"])).fetchone()
        following = db.execute("SELECT note_id FROM companion_materials WHERE creator_id=? "
                               "AND published_at>? ORDER BY published_at LIMIT 1",
                               (row["creator_id"], row["published_at"])).fetchone()
        output.append({"id": row["note_id"], "title": row["title"], "body": row["body"],
                       "ocr": row["ocr"], "replies": json.loads(row["replies"]), "status": row["status"],
                       "published_at": row["published_at"], "updated_at": row["updated_at"],
                       "source": {"platform": "xiaohongshu", "creator_id": row["creator_id"],
                                  "creator_name": row["name"],
                                  "url": "https://www.xiaohongshu.com/explore/" + row["note_id"]},
                       "previous_id": previous[0] if previous else None,
                       "next_id": following[0] if following else None})
    return {"materials": output, "next_cursor": str(rows[-1]["seq"] if rows else cursor),
            "has_more": bool(rows and db.execute("SELECT 1 FROM companion_materials WHERE seq>?",
                                                 (rows[-1]["seq"],)).fetchone()),
            "collection": [dict(r) for r in db.execute("SELECT creator_id,name,last_scan,status,backfill_done "
                                                       "FROM companion_creators ORDER BY creator_id")],
            "source_states": [dict(r) for r in db.execute("SELECT account,scan_status,error,last_scan "
                                                          "FROM sources WHERE name='xhs_creators'")]}
