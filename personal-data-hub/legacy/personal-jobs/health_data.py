"""Read bounded health snapshots from the current hub, with legacy SQLite support."""

import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


def health_rows(database, *, start=None, end=None, latest=False):
    """Return (id, received_at, payload_json), ordered by received_at.

    A configured hub failure is reported, never hidden by stale SQLite data.
    Tokens are read from the existing private file and never logged.
    """
    path = Path(os.environ.get("HERMES_CRON_CONFIG", "/home/yuwk/cron/env/hermes.local.json"))
    settings = json.loads(path.read_text()) if path.exists() else {}
    if not settings.get("health_api_url"):
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=3) as db:
            query = "SELECT id, received_at, payload_json FROM health_payloads"
            clauses, args = [], []
            for operator, value in ((">=", start), ("<", end)):
                if value:
                    clauses.append(f"julianday(received_at) {operator} julianday(?)")
                    args.append(value.isoformat())
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY julianday(received_at)" + (" DESC LIMIT 1" if latest else "")
            return db.execute(query, args).fetchall()

    token = Path(settings["health_token_file"]).read_text().strip()
    if not token:
        raise RuntimeError("health reader token is empty")
    params = {"source": "health", "kind": "health_payloads", "include_content": "true",
              "limit": 1 if latest else 1000, "offset": 0}
    if start:
        params["start"] = start.isoformat()
    if end:
        params["end"] = end.isoformat()
    opener = build_opener(ProxyHandler({}))
    rows = []
    for _ in range(10):
        request = Request(settings["health_api_url"] + "?" + urlencode(params),
                          headers={"Authorization": "Bearer " + token})
        with opener.open(request, timeout=20) as response:
            page = json.load(response)
        for record in page["records"]:
            raw = record["raw"]
            payload = raw["payload_json"]
            rows.append((raw.get("id"), raw["received_at"],
                         payload if isinstance(payload, str) else json.dumps(payload)))
        offset = page.get("next_offset")
        if latest or offset is None:
            return list(reversed(rows))
        if offset <= params["offset"]:
            raise RuntimeError("health pagination did not advance")
        params["offset"] = offset
    raise RuntimeError("health snapshot budget exceeded")
