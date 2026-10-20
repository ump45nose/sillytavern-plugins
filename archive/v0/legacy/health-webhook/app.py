"""
Health Webhook receiver — 2026-07-17

POST /health/import with Bearer token. Stores raw JSON to SQLite.
Reading: Hermes cron job reads /home/hermes/.local/share/health.db.
"""
import json
import os
import sqlite3
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from api_router import router as autoaccounting_router

app = FastAPI(title="health-webhook", version="1.0.0")
app.include_router(autoaccounting_router)

DB_PATH = os.environ.get(
    "HEALTH_WEBHOOK_DB",
    "/home/hermes/.local/share/health.db",
)
TOKEN = os.environ["HEALTH_WEBHOOK_TOKEN"]  # 必须由 systemd EnvironmentFile 注入


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS health_payloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                received_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_health_received_at
                ON health_payloads(received_at)
        """)


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
async def healthz():
    """Liveness probe — 不鉴权。"""
    return {
        "ok": True,
        "service": "health-webhook",
        "ts": datetime.now().astimezone().isoformat(),
    }


@app.post("/health/import")
async def health_import(
    request: Request,
    authorization: str | None = Header(default=None),
):
    expected = f"Bearer {TOKEN}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid json: {e}")

    received_at = datetime.now().astimezone().isoformat()
    payload_json = json.dumps(payload, ensure_ascii=False)

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO health_payloads (received_at, payload_json) VALUES (?, ?)",
            (received_at, payload_json),
        )
        last_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return JSONResponse({
        "ok": True,
        "id": last_id,
        "received_at": received_at,
        "bytes": len(payload_json),
    })


@app.get("/health/recent")
async def health_recent(
    authorization: str | None = Header(default=None),
    limit: int = 10,
):
    """最近 N 条 — 给灵珺本地 inspect 用。"""
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT id, received_at, payload_json FROM health_payloads "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {"id": r[0], "received_at": r[1], "payload": json.loads(r[2])}
        for r in rows
    ]
