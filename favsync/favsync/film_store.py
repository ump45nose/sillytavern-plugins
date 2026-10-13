"""Film leads share Favsync's SQLite while keeping user download state separate."""

from __future__ import annotations

from datetime import date
import sqlite3
import time
import unicodedata

from .film_watchlist import country_info, film_titles, release_info


def init_schema(db: sqlite3.Connection):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS films (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          normalized_title TEXT NOT NULL,
          release_year INTEGER,
          release_date TEXT,
          country TEXT,
          media_type TEXT CHECK(media_type IN ('movie','tv') OR media_type IS NULL),
          downloaded INTEGER NOT NULL DEFAULT 0 CHECK(downloaded IN (0,1)),
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS films_known_title_year
          ON films(normalized_title,release_year) WHERE release_year IS NOT NULL;
        CREATE TABLE IF NOT EXISTS film_sources (
          platform TEXT NOT NULL,
          account TEXT NOT NULL,
          external_id TEXT NOT NULL,
          normalized_title TEXT NOT NULL,
          film_id INTEGER NOT NULL REFERENCES films(id),
          source_title TEXT NOT NULL,
          url TEXT NOT NULL,
          release_year INTEGER,
          release_date TEXT,
          country TEXT,
          active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
          updated_at REAL NOT NULL,
          PRIMARY KEY(platform,account,external_id,normalized_title)
        );
        CREATE INDEX IF NOT EXISTS film_sources_film_id ON film_sources(film_id);
        CREATE TABLE IF NOT EXISTS film_aliases (
          old_id INTEGER PRIMARY KEY,
          new_id INTEGER NOT NULL REFERENCES films(id)
        );
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(films)")}
    if "country" not in columns:
        db.execute("ALTER TABLE films ADD COLUMN country TEXT")
    if "media_type" not in columns:
        db.execute("ALTER TABLE films ADD COLUMN media_type TEXT")
    source_columns = {row[1] for row in db.execute("PRAGMA table_info(film_sources)")}
    if "country" not in source_columns:
        db.execute("ALTER TABLE film_sources ADD COLUMN country TEXT")
        db.execute("""UPDATE film_sources SET country=(
                   SELECT country FROM films WHERE films.id=film_sources.film_id)
                   WHERE platform='manual'""")


def add_manual_film(db: sqlite3.Connection, title: str, year: int,
                    release_date: str | None = None, country: str | None = None,
                    media_type: str | None = None) -> int:
    """建立可去重的手动片单来源，不覆盖已有下载状态。"""
    title = " ".join(unicodedata.normalize("NFKC", title).strip().split())
    normalized = title.casefold()
    now = time.time()
    with db:
        row = db.execute("SELECT id FROM films WHERE normalized_title=? AND release_year=?",
                         (normalized, year)).fetchone()
        film_id = row[0] if row else _new_film(db, title, normalized, year, now)
        db.execute("UPDATE films SET release_date=COALESCE(?,release_date),"
                   "country=COALESCE(?,country),media_type=COALESCE(?,media_type),updated_at=? "
                   "WHERE id=?", (release_date, country, media_type, now, film_id))
        db.execute("""INSERT INTO film_sources
                   (platform,account,external_id,normalized_title,film_id,source_title,url,
                    release_year,release_date,country,active,updated_at)
                   VALUES('manual','api',?,?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(platform,account,external_id,normalized_title) DO UPDATE SET
                   source_title=excluded.source_title,release_date=excluded.release_date,
                   country=COALESCE(excluded.country,film_sources.country),
                   active=1,updated_at=excluded.updated_at""",
                   (str(film_id), normalized, film_id, title, "", year, release_date, country, now))
    return film_id


def _new_film(db, title, normalized, year, now):
    cursor = db.execute(
        "INSERT INTO films(title,normalized_title,release_year,created_at,updated_at) VALUES(?,?,?,?,?)",
        (title, normalized, year, now, now),
    )
    return cursor.lastrowid


def _merge(db, old_id, new_id, now):
    if old_id == new_id:
        return new_id
    old = db.execute("SELECT downloaded FROM films WHERE id=?", (old_id,)).fetchone()
    if old is None:
        return new_id
    db.execute("UPDATE films SET downloaded=MAX(downloaded,?),updated_at=? WHERE id=?",
               (old[0], now, new_id))
    db.execute("UPDATE film_sources SET film_id=? WHERE film_id=?", (new_id, old_id))
    db.execute("UPDATE film_aliases SET new_id=? WHERE new_id=?", (new_id, old_id))
    db.execute("DELETE FROM films WHERE id=?", (old_id,))
    db.execute("INSERT OR REPLACE INTO film_aliases(old_id,new_id) VALUES(?,?)", (old_id, new_id))
    return new_id


def ingest_bilibili(db, account: str, items: list[dict]) -> dict:
    """Commit a complete scan atomically. Missing origins become inactive, not deleted."""
    now = time.time()
    extracted = []
    skipped = 0
    for item in items:
        titles = film_titles(item["title"])
        if not titles:
            skipped += 1
            continue
        release_date, year = release_info(item["intro"])
        country = country_info(item["title"], item["intro"])
        for title, normalized in titles:
            extracted.append((item["bvid"], item["title"], title, normalized,
                              release_date, year, country))
    with db:
        db.execute("UPDATE film_sources SET active=0 WHERE platform='bilibili' AND account=?", (account,))
        touched = set()
        moved = []
        for bvid, source_title, title, normalized, release_date, year, country in extracted:
            origin = db.execute(
                "SELECT film_id FROM film_sources WHERE platform='bilibili' AND account=? "
                "AND external_id=? AND normalized_title=?", (account, bvid, normalized),
            ).fetchone()
            existing_id = origin[0] if origin else None
            if existing_id:
                touched.add(existing_id)
            match = (db.execute("SELECT id FROM films WHERE normalized_title=? AND release_year=?",
                                (normalized, year)).fetchone() if year else None)
            target_id = match[0] if match else None
            if target_id and existing_id and target_id != existing_id:
                other = db.execute("SELECT 1 FROM film_sources WHERE film_id=? AND NOT "
                                   "(platform='bilibili' AND account=? AND external_id=? AND normalized_title=?) LIMIT 1",
                                   (existing_id, account, bvid, normalized)).fetchone()
                film_id = target_id if other else _merge(db, existing_id, target_id, now)
            elif target_id:
                film_id = target_id
            elif existing_id:
                film = db.execute("SELECT release_year FROM films WHERE id=?", (existing_id,)).fetchone()
                if year is not None and film[0] != year:
                    other = db.execute("SELECT 1 FROM film_sources WHERE film_id=? AND NOT "
                                       "(platform='bilibili' AND account=? AND external_id=? AND normalized_title=?) LIMIT 1",
                                       (existing_id, account, bvid, normalized)).fetchone()
                    if other:
                        film_id = _new_film(db, title, normalized, year, now)
                    else:
                        db.execute("UPDATE films SET release_year=?,updated_at=? WHERE id=?",
                                   (year, now, existing_id))
                        film_id = existing_id
                else:
                    film_id = existing_id
            else:
                film_id = _new_film(db, title, normalized, year, now)
            db.execute("""INSERT INTO film_sources
                (platform,account,external_id,normalized_title,film_id,source_title,url,
                 release_year,release_date,country,active,updated_at)
                VALUES('bilibili',?,?,?,?,?,?,?,?,?,1,?)
                ON CONFLICT(platform,account,external_id,normalized_title) DO UPDATE SET
                  film_id=excluded.film_id,source_title=excluded.source_title,
                  url=excluded.url,release_year=excluded.release_year,
                  release_date=excluded.release_date,country=excluded.country,
                  active=1,updated_at=excluded.updated_at""",
                (account, bvid, normalized, film_id, source_title,
                 f"https://www.bilibili.com/video/{bvid}", year, release_date, country, now),
            )
            touched.add(film_id)
            if existing_id and existing_id != film_id:
                moved.append((existing_id, film_id))
        # A delayed date change may leave a source-free record. Keep its old ID as
        # an alias to the moved film, preserving clients' stored references.
        for old_id, new_id in moved:
            if db.execute("SELECT 1 FROM films WHERE id=?", (old_id,)).fetchone() and not db.execute(
                    "SELECT 1 FROM film_sources WHERE film_id=? LIMIT 1", (old_id,)).fetchone():
                _merge(db, old_id, new_id, now)
        for film_id in touched:
            country_row = db.execute("""SELECT country FROM film_sources
                WHERE film_id=? AND active=1 AND country IS NOT NULL
                ORDER BY CASE WHEN platform='manual' THEN 0 ELSE 1 END,
                         release_date ASC, updated_at DESC LIMIT 1""", (film_id,)).fetchone()
            db.execute("UPDATE films SET country=?,updated_at=? WHERE id=?",
                       (country_row[0] if country_row else None, now, film_id))
            dates = [row[0] for row in db.execute(
                "SELECT release_date FROM film_sources WHERE film_id=? AND active=1 AND release_date IS NOT NULL",
                (film_id,),
            )]
            if dates:
                db.execute("UPDATE films SET release_date=?,updated_at=? WHERE id=?",
                           (min(dates), now, film_id))
            elif db.execute("SELECT 1 FROM film_sources WHERE film_id=? AND active=1", (film_id,)).fetchone():
                db.execute("UPDATE films SET release_date=NULL,updated_at=? WHERE id=?", (now, film_id))
    return {"videos": len(items), "titles": len(extracted), "without_title": skipped}


def _row_to_film(db, row, today: date):
    release = row["release_date"]
    sources = [dict(source) for source in db.execute(
        "SELECT platform,external_id,url,active FROM film_sources WHERE film_id=? "
        "ORDER BY active DESC,platform,external_id", (row["id"],))]
    return {
        "id": row["id"], "title": row["title"], "release_year": row["release_year"],
        "release_date": release,
        "country": row["country"], "media_type": row["media_type"],
        "released": date.fromisoformat(release) <= today if release else None,
        "downloaded": bool(row["downloaded"]),
        "active": any(source["active"] for source in sources),
        "sources": [{**source, "active": bool(source["active"])} for source in sources],
    }


def get_film(db, film_id: int, today: date):
    row = db.execute("SELECT * FROM films WHERE id=?", (film_id,)).fetchone()
    if row is None:
        alias = db.execute("SELECT new_id FROM film_aliases WHERE old_id=?", (film_id,)).fetchone()
        if alias:
            row = db.execute("SELECT * FROM films WHERE id=?", (alias[0],)).fetchone()
    return _row_to_film(db, row, today) if row else None


def list_films(db, today: date, offset=0, limit=50, downloaded=None, released=...):
    records = [_row_to_film(db, row, today) for row in db.execute("SELECT * FROM films ORDER BY id")]
    if downloaded is not None:
        records = [item for item in records if item["downloaded"] is downloaded]
    if released is not ...:
        records = [item for item in records if item["released"] is released]
    return {"total": len(records), "offset": offset, "limit": limit,
            "items": records[offset:offset + limit]}


def set_downloaded(db, film_id: int, downloaded: bool, today: date):
    item = get_film(db, film_id, today)
    if item is None:
        return None
    with db:
        db.execute("UPDATE films SET downloaded=?,updated_at=? WHERE id=?",
                   (int(downloaded), time.time(), item["id"]))
    return get_film(db, item["id"], today)


def film_status(db):
    total, downloaded, dated = db.execute(
        "SELECT count(*),coalesce(sum(downloaded),0),count(release_date) FROM films"
    ).fetchone()
    return {"total": total, "downloaded": downloaded, "with_release_date": dated,
            "unknown_release_date": total - dated}
