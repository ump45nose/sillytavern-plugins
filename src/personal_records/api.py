from __future__ import annotations

import hmac
import json
import sqlite3
from contextlib import asynccontextmanager
from decimal import Decimal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from mcp_platform import create_http_app
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .mcp import create_mcp
from .models import Bill, Conflict, HealthDay, NotFound
from .service import Service
from .settings import Settings
from .store import Store


def create_app(settings: Settings | None = None, service: Service | None = None):
    settings = settings or Settings.from_env()
    service = service or Service(Store(settings.database))
    server = create_mcp(service, settings.runtime)
    mcp_app = create_http_app(server, settings.runtime)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(mcp_app):
            yield

    app = FastAPI(title="Personal Records", version="0.1.0", lifespan=lifespan)
    app.state.service, app.state.mcp = service, server

    def matches(authorization, token):
        return bool(authorization) and hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode())

    def read(authorization: str | None = Header(default=None)):
        if not any(matches(authorization, token) for token in (settings.read_token, settings.write_token)):
            raise HTTPException(401, "invalid API credential")

    def write(authorization: str | None = Header(default=None)):
        if not matches(authorization, settings.write_token):
            raise HTTPException(403 if matches(authorization, settings.read_token) else 401, "write permission required")

    @app.exception_handler(NotFound)
    async def missing(request, error): return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, error): return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        detail = error.errors(include_input=False, include_url=False, include_context=False) if isinstance(error, ValidationError) else str(error)
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def unavailable(request, error):
        return JSONResponse({"detail": "database unavailable; request was not acknowledged"}, status_code=503)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "database": service.store.integrity()}

    @app.post("/webhooks/{source}")
    async def webhook(source: str, request: Request, authorization: str | None = Header(default=None)):
        tokens = {"health": settings.health_token, "autoaccounting": settings.accounting_token}
        if source not in tokens: raise NotFound("unknown source")
        if not matches(authorization, tokens[source]): raise HTTPException(401, "invalid source credential")
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise HTTPException(415, "Content-Type must be application/json")
        parts, size = [], 0
        async for part in request.stream():
            size += len(part)
            if size > 16 * 1024 * 1024: raise HTTPException(413, "source payload exceeds 16 MiB")
            parts.append(part)
        def reject_constant(value): raise ValueError("non-finite JSON number")
        payload = json.loads(b"".join(parts), parse_float=Decimal, parse_constant=reject_constant)
        try:
            return await run_in_threadpool(service.store.ingest, source, payload)
        except (KeyError, TypeError, AttributeError, OverflowError) as error:
            raise ValueError("invalid native source payload: missing or invalid field") from error

    @app.get("/api/v1/sources", dependencies=[Depends(read)])
    def sources(): return service.store.source_status()

    @app.get("/api/v1/health/summary", dependencies=[Depends(read)])
    def health_summary(start_date: str, end_date: str, metrics: list[str] | None = Query(default=None)):
        return service.health_summary(start_date, end_date, metrics)

    @app.get("/api/v1/health/days", dependencies=[Depends(read)])
    def health_days(start_date: str | None = None, end_date: str | None = None, offset: int = 0, limit: int = 50):
        return service.list_health_days(start_date, end_date, offset, limit)

    @app.post("/api/v1/health/days", status_code=201, dependencies=[Depends(write)])
    def create_health(record: HealthDay): return service.create_health_day(record.model_dump(exclude_none=True))

    @app.get("/api/v1/health/days/{selected}", dependencies=[Depends(read)])
    def get_health(selected: str): return service.get_health_day(selected)

    @app.patch("/api/v1/health/days/{selected}", dependencies=[Depends(write)])
    def update_health(selected: str, patch: dict): return service.update_health_day(selected, patch)

    @app.delete("/api/v1/health/days/{selected}", dependencies=[Depends(write)])
    def delete_health(selected: str): return service.delete_health_day(selected)

    def bill_filters(start_date: str | None = None, end_date: str | None = None, type: str | None = None,
                     currency: str | None = None, category: str | None = None, book: str | None = None,
                     account: str | None = None, account_from: str | None = None, account_to: str | None = None,
                     status: str | None = None, query: str | None = None):
        return dict(start_date=start_date, end_date=end_date, type=type, currency=currency, category=category,
            book=book, account=account, account_from=account_from, account_to=account_to, status=status, query=query)

    @app.get("/api/v1/bills/summary", dependencies=[Depends(read)])
    def bill_summary(start_date: str, end_date: str, group_by: str | None = None, filters: dict = Depends(bill_filters)):
        filters.pop("start_date"); filters.pop("end_date")
        return service.bill_summary(start_date, end_date, group_by, **filters)

    @app.get("/api/v1/bills", dependencies=[Depends(read)])
    def bills(offset: int = 0, limit: int = 50, filters: dict = Depends(bill_filters)):
        return service.list_bills(offset=offset, limit=limit, **filters)

    @app.post("/api/v1/bills", status_code=201, dependencies=[Depends(write)])
    def create_bill(record: Bill): return service.create_bill(record.model_dump())

    @app.get("/api/v1/bills/{identifier}", dependencies=[Depends(read)])
    def get_bill(identifier: str): return service.get_bill(identifier)

    @app.patch("/api/v1/bills/{identifier}", dependencies=[Depends(write)])
    def update_bill(identifier: str, patch: dict): return service.update_bill(identifier, patch)

    @app.delete("/api/v1/bills/{identifier}", dependencies=[Depends(write)])
    def delete_bill(identifier: str): return service.delete_bill(identifier)

    app.mount("/", mcp_app)
    return app
