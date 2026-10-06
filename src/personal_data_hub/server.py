from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .contracts import Asset, Batch, Record, canonical, digest, instant, utcnow
from .runner import configuration, store_from


class RecordInput(BaseModel):
    external_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    raw: dict
    normalized: dict = Field(default_factory=dict)
    occurred_at: str | None = None
    updated_at: str | None = None
    timezone: str = "Asia/Shanghai"
    assets: list[dict] = Field(default_factory=list)


class BatchInput(BaseModel):
    batch_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    records: list[RecordInput] = Field(default_factory=list, max_length=1000)
    deletions: list[str] = Field(default_factory=list, max_length=1000)
    next_cursor: dict | None = None


def create_app(config=None, crm_settings=None, webhook_only=False):
    config = config or configuration()
    store = store_from(config)
    from sqlalchemy import Sequence, select
    from .storage import records as archive_records
    health_ids = Sequence("hub_health_ids")
    if store.engine.dialect.name == "postgresql":
        with store.engine.begin() as c:
            c.execute(__import__("sqlalchemy").text("SELECT pg_advisory_xact_lock(:key)"), {"key": store.lock_id("health-id-sequence")})
            existing = c.scalar(__import__("sqlalchemy").text("SELECT to_regclass('hub_health_ids')"))
            if existing is None:
                legacy = list(c.scalars(select(archive_records.c.raw).where(archive_records.c.source == "health")))
                maximum = max([int(r.get("id", 0)) for r in legacy] + [0])
                Sequence("hub_health_ids", start=maximum + 1).create(c)
    for source, settings in config["sources"].items():
        store.register(source, settings.get("account", "owner"), settings["adapter"], settings.get("deletion_support", "explicit_only"))
    if webhook_only:
        app = FastAPI(title="Personal Data Hub ingest")
        @app.get("/healthz")
        def healthz(): return {"status": "ok"}
    else:
        from personal_crm.app.server import create_app as crm_app
        from personal_crm.app.settings import Settings
        from personal_crm.storage import CrmRepository
        settings = crm_settings or Settings()
        settings.database_url = str(store.engine.url)
        # URL 对象的 str 默认隐藏密码，原始连接值必须来自配置。
        settings.database_url = config.get("database_url") or os.environ["HUB_DATABASE_URL"]
        settings.reminder_scheduler_enabled = False
        settings.chat_events_enabled = False
        settings.daily_review_events_enabled = False
        repository = CrmRepository(settings.database_url, hub_store=store)
        app = crm_app(settings, repository, hub_store=store)
    app.state.hub_store = store
    api = APIRouter()

    def secret(name):
        if config.get(name + "_file"):
            return Path(config[name + "_file"]).read_text().strip()
        return os.environ.get(name.upper(), "")

    def authenticate(authorization, name="hub_api_token"):
        token = secret(name)
        if not token: raise HTTPException(503, "authentication_not_configured")
        if not authorization or not hmac.compare_digest(authorization, "Bearer " + token): raise HTTPException(401, "unauthorized")

    @api.get("/api/v1/sources")
    def data_sources(authorization: str | None = Header(default=None)):
        authenticate(authorization); return store.status()

    @api.get("/api/v1/records")
    def data_records(source: str | None = None, kind: str | None = None, offset: int = 0, limit: int = 100, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        try: return {"records": store.list_records(source, kind, offset, limit)}
        except ValueError: raise HTTPException(422, "invalid_pagination") from None

    @api.get("/api/v1/records/{record_id}")
    def data_record(record_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        result = store.get_record(record_id)
        if result is None: raise HTTPException(404, "record_not_found")
        return result

    @api.get("/api/v1/assets/{asset_id}")
    def download(asset_id: str, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        path = store.asset_path(asset_id)
        if path is None: raise HTTPException(404, "asset_not_found")
        return FileResponse(path, media_type="application/octet-stream")

    @api.put("/api/v1/assets/{asset_id}")
    async def upload(asset_id: str, request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        if len(asset_id) != 64 or any(x not in "0123456789abcdef" for x in asset_id): raise HTTPException(422, "invalid_asset_hash")
        fd, tmp_name = tempfile.mkstemp(dir=store.root, prefix=".upload-")
        path = Path(tmp_name); h = hashlib.sha256(); size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                async for block in request.stream():
                    size += len(block)
                    if size > 8 * 1024 ** 3: raise HTTPException(413, "asset_too_large")
                    h.update(block); out.write(block)
                out.flush(); os.fsync(out.fileno())
            if h.hexdigest() != asset_id: raise HTTPException(422, "asset_hash_mismatch")
            with store.lock("hub-asset-and-record-writer"):
                store.put_asset(Asset(asset_id, path=path))
            return {"asset_id": asset_id, "size": size}
        finally: path.unlink(missing_ok=True)

    @api.post("/api/v1/ingest")
    def ingest(payload: BatchInput, authorization: str | None = Header(default=None)):
        authenticate(authorization)
        if payload.source not in config["sources"]: raise HTTPException(422, "unknown_source")
        items = []
        for item in payload.records:
            attachments = []
            for a in item.assets:
                key = str(a.get("id", ""))
                if len(key) != 64 or any(x not in "0123456789abcdef" for x in key): raise HTTPException(422, "invalid_asset_hash")
                p = store.root / key[:2] / key
                if not p.is_file(): raise HTTPException(409, "asset_not_uploaded")
                attachments.append(Asset(a.get("name", key), path=p, media_type=a.get("media_type", "application/octet-stream")))
            items.append(Record(item.external_id, item.kind, item.raw, item.normalized, instant(item.occurred_at), instant(item.updated_at), item.timezone, attachments))
        with store.lock("source:" + payload.source):
            result = store.ingest(payload.source, Batch(items, payload.deletions, payload.next_cursor))
        return {"batch_id": payload.batch_id, "accepted": len(items), "committed": True, **result}

    @api.get("/health")
    def health(): return {"ok": True, "service": "personal-data-hub", "ts": utcnow().isoformat()}

    @api.post("/health/import")
    async def health_import(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization, "health_webhook_token")
        payload = await request.json(); received = utcnow()
        eid = request.headers.get("Idempotency-Key") or "payload:" + digest(payload)
        with store.lock("source:health"):
            previous = store.get_record(store.identity("health", eid))
            if previous:
                identifier = previous["raw"].get("id")
                received = instant(previous["raw"]["received_at"])
            elif store.engine.dialect.name == "postgresql":
                with store.engine.begin() as c: identifier = c.scalar(health_ids.next_value())
            else:
                identifier = len(store.list_records("health", limit=1000)) + 1
            store.ingest("health", Batch(records=[Record(eid, "health_payloads", {"id": identifier, "payload_json": payload, "received_at": received.isoformat()}, {"payload": payload, "missing_is_zero": False}, received)]))
        return {"ok": True, "id": identifier, "received_at": received.isoformat(), "bytes": len(canonical(payload).encode())}

    @api.get("/health/recent")
    def health_recent(limit: int = 10, authorization: str | None = Header(default=None)):
        authenticate(authorization, "health_webhook_token")
        return [{"id": r["raw"].get("id"), "received_at": r["raw"].get("received_at"), "payload": r["raw"].get("payload_json")} for r in store.list_records("health", "health_payloads", limit=limit)]

    @api.post("/autoaccounting/v1/bills")
    async def bill_import(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization, "autoaccounting_webhook_token")
        from .bill_contract import validate_bill
        payload = await request.json()
        try: bill = validate_bill(payload)
        except ValueError: raise HTTPException(422, "invalid_bill") from None
        result = store.ingest("finance", Batch(records=[Record(str(bill["id"]), "bill", {"bill": bill}, {"currency": bill.get("currency"), "amount": str(bill["money"]), "type": bill["type"]}, instant(bill["time"] / 1000))]))
        return {"ok": True, "bill_id": bill["id"], "changed": bool(result["changed"]), "date": instant(bill["time"] / 1000).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Shanghai")).date().isoformat()}

    @api.post("/autoaccounting/v1/deletions")
    async def bill_delete(request: Request, authorization: str | None = Header(default=None)):
        authenticate(authorization, "autoaccounting_webhook_token")
        payload = await request.json()
        ids = payload.get("bill_ids", [])
        if not isinstance(ids, list) or not ids or len(ids) > 1000 or any(not isinstance(x, int) or isinstance(x, bool) or x <= 0 for x in ids): raise HTTPException(422, "invalid_bill_ids")
        return {"ok": True, **store.ingest("finance", Batch(deletions=[str(x) for x in ids]))}

    @api.get("/autoaccounting/v1/bills/ids")
    def bill_ids(offset: int = 0, limit: int = 1000, authorization: str | None = Header(default=None)):
        authenticate(authorization, "autoaccounting_webhook_token")
        if offset < 0 or not 1 <= limit <= 1000: raise HTTPException(422, "invalid_pagination")
        with store.engine.connect() as c:
            ids = list(c.scalars(select(archive_records.c.external_id).where(archive_records.c.source == "finance", archive_records.c.kind == "bill").order_by(archive_records.c.external_id).offset(offset).limit(limit)))
        return {"ok": True, "bill_ids": [int(x) for x in ids], "next_offset": offset + len(ids) if len(ids) == limit else None}

    # 既有 CRM 根挂载必须排在新增 API 后面。
    mount = app.router.routes.pop() if not webhook_only else None
    app.include_router(api)
    if mount: app.router.routes.append(mount)
    return app


def main():
    import uvicorn
    uvicorn.run(create_app(webhook_only=os.environ.get("HUB_WEBHOOK_ONLY") == "1"), host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8080")))
