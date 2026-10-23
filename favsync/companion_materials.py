"""Budgeted creator text collection using shared requests and private persistence."""
import json
import logging
import re
import time

from .common import SyncError
from .companion_store import CompanionStore

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


def meaningful(text):
    return re.sub(r"#[^\s#]+(?:\[话题\])?#?", "", text or "").strip()


def stamp(note):
    value = float(note.get("time") or note.get("publish_time") or 0)
    return value / 1000 if value > 100000000000 else value


def sync_creators(adapter, store, section):
    repository = CompanionStore(store.db)
    configured = section.get("creators", [{"id": i, "name": n} for i, n in CREATORS])
    for item in configured:
        if not re.fullmatch(r"[0-9a-f]{24}", item["id"]):
            raise SyncError("invalid_export")
    authors = repository.authors(configured)
    cutoff = time.time() - 90 * 86400
    remaining = min(2, adapter.detail_remaining)
    for author in authors:
        author_id = author["creator_id"]
        # Alternate head refresh and incremental archive pages; newest pending wins.
        cursor = author["cursor"] if author["scan_count"] % 2 and not author["backfill_done"] else ""
        repository.start_scan(author_id)
        page = adapter.request("user-posts", author_id, "--cursor", cursor, timeout=120)
        notes = page.get("notes") or page.get("items") or []
        adapter.observe("scan_pages")
        records = []
        for note in notes:
            note_id = str(note.get("note_id") or note.get("id") or "")
            published = stamp(note)
            if not re.fullmatch(r"[0-9a-f]{24}", note_id) or published < cutoff:
                continue
            status = "skipped_video" if note.get("type") == "video" else "pending"
            locator = {"token": note.get("xsec_token", ""), "title": note.get("display_title", "")}
            records.append((note_id, published, locator, status))
        next_cursor = str(page.get("cursor") or "")
        done = not page.get("has_more", False) or bool(notes and all(stamp(n) < cutoff for n in notes))
        repository.save_page(author, records, next_cursor, done, advance=bool(cursor or not author["cursor"]))
        # Reserve at most two details, and periodically refresh the latest cache.
        pending = repository.next_note(author, cutoff, adapter.cfg["xhs"]["detail_cache_ttl_seconds"])
        if pending is not None and remaining:
            remaining -= 1
            locator = json.loads(pending["locator"])
            note = repository.cached_note(pending["note_id"], adapter.cfg["xhs"]["detail_cache_ttl_seconds"])
            if note is None:
                adapter.reserve_detail()
                data = adapter.request("read", pending["note_id"], "--xsec-token", locator["token"], timeout=120)
                note = data.get("note") or data.get("note_card") or data
                if "items" in note:
                    note = note["items"][0].get("note_card", note["items"][0])
                repository.cache_note(pending["note_id"], note)
            save_note(adapter, repository, pending, note, locator)
    store.update("xhs_creators", section["account"], scan_status="cached", error=None, last_scan=time.time())


def save_note(adapter, repository, pending, note, locator):
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
                text = image_text(repository.db, url)
                if text:
                    ocr.append(text)
            except Exception as exc:
                status = "ocr_failed"
                logging.getLogger("favsync").warning("companion OCR: %s (cached body retained)", type(exc).__name__)
        if not ocr and len(meaningful(body)) < 40:
            status = "insufficient_text" if status == "ready" else status
    if status == "ocr_failed" and repository.retain_ready(pending["note_id"]):
        return
    replies = []
    comments = repository.cached_comments(pending["note_id"])
    if comments is None:
        comments = adapter.request("comments", pending["note_id"], "--xsec-token", locator["token"], timeout=120)
    for comment in (comments.get("comments") or [])[:30]:
        candidates = [comment, *(comment.get("sub_comments") or [])[:5]]
        for reply in candidates:
            user = reply.get("user_info") or reply.get("user") or {}
            if str(user.get("user_id") or user.get("id")) == pending["creator_id"]:
                text = str(reply.get("content") or "")[:600]
                if text and len(replies) < 5:
                    replies.append(text)
    repository.save_material(pending, stamp(note) or pending["published_at"], title,
                             body, "\n".join(ocr), replies, status, comments)
