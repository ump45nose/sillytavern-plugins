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
from .sources.usage import Usage
from .sources.media import Media
from .sources.github import GitHub
from .sources.review import Review
from .review_routes import register as review_routes
from .media_routes import register as media_routes
from .personal_routes import register as personal_routes
from .auth import register as auth_routes
from .store import Store
from .configuration import register as configuration_routes, preferences, subscriptions
from .attention import register as attention_routes

ZONE = ZoneInfo("Asia/Shanghai")


def create_app(settings=None, adapters=None, now=None, transport=None):
    settings = settings or Settings()
    now = now or (lambda: datetime.now(ZONE))
    if settings.oidc_issuer and settings.dev_token:
        raise ValueError('OIDC and development authentication must not be enabled together')
    store = Store(settings.database)
    async def discard_cookies(request):
        # Bearer sources can share a LAN IP across ports; never forward one source's cookies.
        request.headers.pop("cookie", None)
    client = httpx.AsyncClient(timeout=settings.source_timeout_seconds, transport=transport, follow_redirects=False,
                               event_hooks={"request": [discard_cookies]})
    media = Media(client, settings, now, transport)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await client.aclose()
        await media.qbit.aclose()

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
    personal = Personal(client, settings, now, lambda: preferences(store))
    review = Review(client, settings)
    defaults = {a.id: a for a in Records(client, settings, now, lambda: subscriptions(store)).adapters() + personal.adapters() + Usage(client, settings).adapters() + media.adapters() + [GitHub(client, settings, now).adapter(),review.adapter()]}
    for identifier in dict.fromkeys(s for ids in MODULE_SOURCES.values() for s in ids):
        defaults.setdefault(identifier, Adapter(identifier, identifier, 120 if identifier == "github" else 30))
    manager = SourceManager(adapters if adapters is not None else list(defaults.values()), now, settings.source_timeout_seconds)
    manager.store, manager.module_sources = store, MODULE_SOURCES
    manager.media_links = {s: getattr(settings, s + "_public_url") for s in ("emby", "navidrome", "moviepilot", "qbittorrent")}
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
    async def module(identifier: str, range: str = "day"):
        if range not in ("day", "week", "month", "year"):
            raise HTTPException(400)
        if identifier not in MODULE_SOURCES:
            raise HTTPException(404)
        return (await modules(manager, [identifier], token_range=range))[identifier]

    @app.get("/api/v1/devices", dependencies=[Depends(authenticated)])
    def devices():
        return {"devices": store.devices()}

    @app.delete("/api/v1/devices/{identifier}", status_code=204, dependencies=[Depends(authenticated)])
    def revoke(identifier: str):
        if not store.revoke(identifier):
            raise HTTPException(404)
        from fastapi.responses import Response
        return Response(status_code=204)

    auth_routes(app, settings, store, client, now)
    configuration_routes(app, store, manager, authenticated, now)
    attention_routes(app, manager, authenticated, now)
    personal_routes(app, settings, personal, authenticated, now, manager)
    review_routes(app, review, settings, manager, authenticated)
    media_routes(app, settings, media, authenticated)
    return app
