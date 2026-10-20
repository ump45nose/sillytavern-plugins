import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .modules import MODULE_SOURCES, modules
from .settings import Settings
from .sources.base import Adapter, SourceManager
from .sources.records import Records
from .sources.personal import Personal
from .personal_routes import register as personal_routes
from .store import Store

ZONE = ZoneInfo("Asia/Shanghai")


def create_app(settings=None, adapters=None, now=None, transport=None):
    settings = settings or Settings()
    now = now or (lambda: datetime.now(ZONE))
    store = Store(settings.database)
    client = httpx.AsyncClient(timeout=settings.source_timeout_seconds, transport=transport, follow_redirects=False)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()

    class SafeJSONResponse(JSONResponse):
        def render(self, content):
            # Source content is untrusted too: never echo configured credentials.
            def scrub(value):
                if isinstance(value, str):
                    for secret in settings.secrets():
                        value = value.replace(secret, "[redacted]")
                    return value
                if isinstance(value, list):
                    return [scrub(v) for v in value]
                if isinstance(value, dict):
                    return {scrub(k): scrub(v) for k, v in value.items()}
                return value
            return super().render(scrub(content))

    app = FastAPI(title="Personal Hub", lifespan=lifespan, default_response_class=SafeJSONResponse)
    personal = Personal(client, settings, now)
    defaults = {a.id: a for a in Records(client, settings, now).adapters() + personal.adapters()}
    for identifier in dict.fromkeys(s for ids in MODULE_SOURCES.values() for s in ids):
        defaults.setdefault(identifier, Adapter(identifier, identifier, 120 if identifier == "github" else 30))
    manager = SourceManager(adapters if adapters is not None else list(defaults.values()), now, settings.source_timeout_seconds)
    app.state.store, app.state.sources, app.state.client = store, manager, client

    def error(status):
        codes = {400: "bad_request", 401: "unauthorized", 403: "unauthorized", 404: "not_found", 409: "conflict", 422: "bad_request", 429: "bad_request"}
        return SafeJSONResponse({"error": {"code": codes.get(status, "upstream"), "message": codes.get(status, "upstream")}}, status_code=status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return error(exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(400)

    @app.exception_handler(Exception)
    async def server_error(request, exc):
        return error(500)

    def authenticated(authorization: str | None = Header(default=None)):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401)
        token = authorization[7:]
        if settings.dev_token and hmac.compare_digest(token.encode(), settings.dev_token.get_secret_value().encode()):
            return "development"
        device = store.authenticate(token, now().isoformat())
        if not device:
            raise HTTPException(401)
        return device

    @app.get("/healthz")
    def healthz():
        with store.connection() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/v1/status", dependencies=[Depends(authenticated)])
    def status():
        return {"sources": [manager.status(s) for s in manager.adapters]}

    @app.get("/api/v1/modules", dependencies=[Depends(authenticated)])
    async def batch(ids: str | None = None):
        selected = list(dict.fromkeys(ids.split(","))) if ids else list(MODULE_SOURCES)
        if any(s not in MODULE_SOURCES for s in selected):
            raise HTTPException(400)
        return {"modules": await modules(manager, selected)}

    @app.get("/api/v1/modules/{identifier}", dependencies=[Depends(authenticated)])
    async def module(identifier: str):
        if identifier not in MODULE_SOURCES:
            raise HTTPException(404)
        return (await modules(manager, [identifier]))[identifier]

    @app.get("/api/v1/devices", dependencies=[Depends(authenticated)])
    def devices():
        return {"devices": store.devices()}

    @app.delete("/api/v1/devices/{identifier}", status_code=204, dependencies=[Depends(authenticated)])
    def revoke(identifier: str):
        if not store.revoke(identifier):
            raise HTTPException(404)
        from fastapi.responses import Response
        return Response(status_code=204)

    personal_routes(app, settings, personal, authenticated, now, manager)
    return app
