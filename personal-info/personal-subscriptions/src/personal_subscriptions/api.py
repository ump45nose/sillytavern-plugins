import hmac
import json
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from mcp_platform import authorize, create_http_app, create_server
from pydantic import ValidationError

from .models import Conflict, NotFound, Subscription
from .settings import Settings
from .store import Store
from .brands import BRANDS, ICON_DIRECTORY, catalog


def create_app(settings=None, store=None):
    settings = settings or Settings.from_env()
    store = store or Store(settings.database)
    server = create_server(settings.runtime, instructions="管理多账号订阅及最新额度。金额为原币十进制字符串，未知不等于免费；公司费用不计个人支出。修改和删除须提供读取时的版本。采集状态与读数时间分开，查询不触发采集。")
    read_auth, write_auth = authorize("read", settings.runtime), authorize("write", settings.runtime)

    @server.tool(auth=read_auth)
    def list_subscriptions(offset: int = 0, limit: int = 50, category: str | None = None) -> dict:
        """分页列出订阅、账号及最新额度，category 为 ai/network/membership/other。"""
        return store.list(offset, limit, category)

    @server.tool(auth=read_auth)
    def get_subscription(id: str) -> dict:
        """读取一条订阅及其版本和额度状态。"""
        return store.get(id)

    @server.tool(auth=write_auth)
    def create_subscription(record: Subscription) -> dict:
        """登记付费或免费订阅，不会登录供应商或自动选择账号。"""
        return store.create(record)

    @server.tool(auth=write_auth)
    def update_subscription(id: str, patch: dict, version: int) -> dict:
        """按版本修改指定资料；省略字段保持原值，null 清除可空字段。"""
        return store.update(id, patch, version)

    @server.tool(auth=write_auth)
    def delete_subscription(id: str, version: int) -> dict:
        """按版本删除订阅及最新额度；停止此条关联采集。"""
        return store.delete(id, version)

    @server.tool(auth=read_auth)
    def list_subscription_sources() -> dict:
        """读取最近采集发现的来源账号，供明确关联；不包含凭据。"""
        return store.catalog()

    @server.tool(auth=read_auth)
    def list_subscription_brands() -> dict:
        """列出可选品牌、内置图标、默认主题色及官网；品牌与额度采集互相独立。"""
        return catalog()

    @server.tool(auth=read_auth)
    def summarize_subscriptions() -> dict:
        """汇总原币与参考汇率换算的个人预计月费；不包含一次性、公司和付款方未知的记录。"""
        return store.summary()

    mcp = create_http_app(server, settings.runtime)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.lifespan(mcp): yield

    app = FastAPI(title="Personal Subscriptions", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.mcp = store, server

    def matches(value, token):
        return bool(value) and hmac.compare_digest(value.encode(), ("Bearer "+token).encode())

    def read(authorization: str | None = Header(default=None)):
        if not any(matches(authorization, t) for t in (settings.read_token, settings.write_token)): raise HTTPException(401)

    def write(authorization: str | None = Header(default=None)):
        if not matches(authorization, settings.write_token):
            raise HTTPException(403 if matches(authorization, settings.read_token) else 401)

    @app.exception_handler(NotFound)
    async def missing(request, error): return JSONResponse({"detail": str(error)}, status_code=404)

    @app.exception_handler(Conflict)
    async def conflict(request, error): return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        detail = error.errors(include_input=False, include_url=False, include_context=False) if isinstance(error, ValidationError) else "invalid request"
        return JSONResponse({"detail": detail}, status_code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def unavailable(request, error): return JSONResponse({"detail": "database unavailable"}, status_code=503)

    async def body(request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 65536: raise HTTPException(413)
        data = json.loads(raw)
        if not isinstance(data, dict): raise ValueError("object required")
        return data

    @app.get("/healthz")
    def health(): return {"status": "ok", "database": store.integrity()}

    @app.get("/api/v1/sources", dependencies=[Depends(read)])
    def sources(): return store.catalog()

    @app.get("/api/v1/subscriptions", dependencies=[Depends(read)])
    def listing(offset: int = 0, limit: int = 50, category: str | None = None): return store.list(offset, limit, category)

    @app.get("/api/v1/subscriptions/summary", dependencies=[Depends(read)])
    def summary(): return store.summary()

    @app.get("/api/v1/subscriptions/brands", dependencies=[Depends(read)])
    def brands(): return catalog()

    @app.get("/api/v1/subscriptions/icons/{service_key}.png", dependencies=[Depends(read)])
    def icon(service_key: str):
        if service_key not in BRANDS: raise HTTPException(404)
        return FileResponse(ICON_DIRECTORY / (service_key + ".png"), media_type="image/png",
                            headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})

    @app.get("/api/v1/subscriptions/{identifier}", dependencies=[Depends(read)])
    def detail(identifier: str): return store.get(identifier)

    @app.post("/api/v1/subscriptions", dependencies=[Depends(write)], status_code=201)
    async def create(request: Request): return store.create(await body(request))

    def version(value):
        if not value or not value.isdecimal() or len(value)>12: raise HTTPException(428, "If-Match version required")
        return int(value)

    @app.patch("/api/v1/subscriptions/{identifier}", dependencies=[Depends(write)])
    async def update(identifier: str, request: Request, if_match: str | None = Header(default=None)):
        return store.update(identifier, await body(request), version(if_match))

    @app.delete("/api/v1/subscriptions/{identifier}", dependencies=[Depends(write)])
    def delete(identifier: str, if_match: str | None = Header(default=None)):
        return store.delete(identifier, version(if_match))

    app.mount("/", mcp)
    return app
