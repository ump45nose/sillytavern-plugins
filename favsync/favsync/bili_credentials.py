"""Read-only boundary to the deployed bili-sync credential schema."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .common import SyncError


def read_bili_sync_credential(database):
    path = Path(database)
    if not path.is_file():
        raise SyncError("bili_sync_unavailable")
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
            row = db.execute("SELECT data FROM config ORDER BY id DESC LIMIT 1").fetchone()
        credentials = json.loads(row[0])["credential"] if row else {}
        uid = str(credentials.get("dedeuserid") or "")
        sessdata = credentials.get("sessdata")
        if not uid.isdecimal() or not sessdata:
            raise SyncError("auth_required")
        return uid, credentials
    except (sqlite3.Error, OSError, ValueError, KeyError, TypeError) as exc:
        raise SyncError("bili_sync_unavailable") from exc

