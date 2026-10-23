import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
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
from .sources.subscriptions import Subscriptions
from .subscription_routes import register as subscription_routes
from .review_routes import register as review_routes
from .media_routes import register as media_routes
from .personal_routes import register as personal_routes
from .memo_routes import register as memo_routes
from .sources.memos import Memos
from .auth import register as auth_routes
from .store import Store
from .context import HubContext
from .configuration import register as configuration_routes, preferences
from .attention import register as attention_routes
from .sync import register as sync_routes, configured_bindings
from .computer_history import register as computer_history_routes

ZONE = ZoneInfo("Asia/Shanghai")


def create_app(settings=None, adapters=None, now=None, transport=None):
    settings = settings or Settings()
    now = now or (lambda: datetime.now(ZONE))
    if settings.oidc_issuer and settings.dev_token:
        raise ValueError('OIDC and development authentication must not be enabled together')
    if bool(settings.owner_issuer) != bool(settings.owner_subject):
        raise ValueError('owner_issuer and owner_subject must be configured together')
    owner = (settings.owner_issuer.rstrip('/'), settings.owner_subject) if settings.owner_subject else None
    if settings.dev_token and owner is None:
        owner = ('urn:hub:development', 'development')
    store = Store(settings.database, owner)
    store.configure_bindings(configured_bindings(settings, store))
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
    memos = Memos(personal)
    review = Review(client, settings)
    subscription_source = Subscriptions(client, settings)
    defaults = {a.id: a for a in Records(client, settings, now).adapters() + personal.adapters() + Usage(client, settings, now).adapters() + [Adapter("memos", "Memos", 60, memos.module if settings.memos_token else None)] + media.adapters() + [GitHub(client, settings, now).adapter(),review.adapter(),subscription_source.adapter()]}
    for identifier in dict.fromkeys(s for ids in MODULE_SOURCES.values() for s in ids):
        defaults.setdefault(identifier, Adapter(identifier, identifier, 120 if identifier == "github" else 30))
    manager = SourceManager(adapters if adapters is not None else list(defaults.values()), now, settings.source_timeout_seconds)
    context = HubContext(manager, store, MODULE_SOURCES,
        {s: getattr(settings, s + "_public_url") for s in ("emby", "navidrome", "moviepilot", "qbittorrent")})
    app.state.hub = context
    app.state.store, app.state.sources, app.state.client = store, manager, client

    def error(status):
        codes = {400: "bad_request", 401: "unauthorized", 403: "unauthorized", 404: "not_found", 409: "conflict", 410: "retired", 428: "version_required", 422: "bad_request", 429: "bad_request"}
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
            return {'user_id':store.owner_id, 'device_id':'development'}
        device = store.authenticate(token, now().isoformat())
        if not device:
            raise HTTPException(401)
        return device

    def source_authenticated(identity=Depends(authenticated)):
        # The existing adapters and their caches belong to one configured owner.
        # Additional identities get state APIs, never these instance credentials.
        if identity['user_id'] != store.owner_id:
            raise HTTPException(403)
        return identity

    @app.get("/healthz")
    def healthz():
        with store.connection() as db:
            db.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/api/v1/status")
    def status(identity=Depends(authenticated)):
        return {"sources": [manager.status(s) for s in manager.adapters] if identity['user_id']==store.owner_id else []}

    @app.get("/api/v1/modules", dependencies=[Depends(source_authenticated)])
    async def batch(ids: str | None = None):
        selected = list(dict.fromkeys(ids.split(","))) if ids else list(MODULE_SOURCES)
        if any(s not in MODULE_SOURCES for s in selected):
            raise HTTPException(400)
        return {"modules": await modules(context, selected)}

    @app.get("/api/v1/modules/{identifier}", dependencies=[Depends(source_authenticated)])
    async def module(identifier: str, range: str = "day"):
        if range not in ("day", "week", "month", "year"):
            raise HTTPException(400)
        if identifier not in MODULE_SOURCES:
            raise HTTPException(404)
        return (await modules(context, [identifier], token_range=range))[identifier]

    @app.get("/api/v1/devices", dependencies=[Depends(authenticated)])
    def devices(identity=Depends(authenticated)):
        return {"devices": store.devices(identity['user_id'])}

    @app.delete("/api/v1/devices/{identifier}", status_code=204, dependencies=[Depends(authenticated)])
    def revoke(identifier: str, identity=Depends(authenticated)):
        if not store.revoke(identifier, identity['user_id'], now().isoformat()):
            raise HTTPException(404)
        from fastapi.responses import Response
        return Response(status_code=204)

    auth_routes(app, settings, store, client, now)
    configuration_routes(app, store, context, authenticated, now, source_authenticated)
    sync_routes(app, settings, store, authenticated, now)
    computer_history_routes(app, settings, store, source_authenticated, now)
    subscription_routes(app, subscription_source, settings, manager, source_authenticated)
    attention_routes(app, context, source_authenticated, now)
    personal_routes(app, settings, personal, source_authenticated, now, manager)
    memo_routes(app, settings, memos, source_authenticated, manager)
    review_routes(app, review, settings, manager, source_authenticated)
    media_routes(app, settings, media, source_authenticated)
    return app
