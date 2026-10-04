"""统一启动、HTTP 生命周期、权限和仅含元数据的审计。"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import pydantic_core
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware.authorization import AuthMiddleware

from .auth import authorize, build_provider, claims
from .config import RuntimeConfig


class PolicyMiddleware(Middleware):
    def __init__(self, config):
        self.config = config
        self.windows = defaultdict(deque)

    async def on_call_tool(self, context, call_next):
        cfg = self.config
        token = get_access_token()
        identity = claims(token)
        subject = str(identity.get("sub") or identity.get("preferred_username") or "local")
        subject_id = hmac.new(cfg.jwt_signing_key.get_secret_value().encode(),
                              subject.encode(), hashlib.sha256).hexdigest()[:16]
        started, status = time.monotonic(), "error"
        try:
            if cfg.requests_per_minute:
                window = self.windows[subject_id]
                while window and window[0] <= started - 60:
                    window.popleft()
                if len(window) >= cfg.requests_per_minute:
                    raise ToolError("rate_limited: 请求过于频繁")
                window.append(started)
            try:
                if cfg.tool_timeout_seconds:
                    async with asyncio.timeout(cfg.tool_timeout_seconds):
                        result = await call_next(context)
                else:
                    result = await call_next(context)
            except TimeoutError:
                status = "outcome_unknown"
                raise ToolError("outcome_unknown: 调用超时，执行结果未知；不要自动重试写入") from None
            if cfg.max_output_bytes and len(pydantic_core.to_json(result, fallback=str)) > cfg.max_output_bytes:
                raise ToolError("output_too_large: 请缩小查询范围；工具可能已执行，勿重试写入")
            status = "ok"
            return result
        finally:
            if cfg.audit_enabled:
                logging.getLogger("mcp_platform.audit").info(json.dumps({
                    "subject": subject_id, "tool": context.message.name,
                    "duration_ms": round((time.monotonic() - started) * 1000), "status": status,
                }))


def create_server(config: RuntimeConfig, *, instructions=None, lifespan=None,
                  healthcheck=None) -> FastMCP:
    if config.audit_enabled:
        logger = logging.getLogger("mcp_platform.audit")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            logger.addHandler(logging.StreamHandler())
        logger.propagate = False
    provider, store = build_provider(config)

    @asynccontextmanager
    async def lifetime(server):
        try:
            if lifespan is not None:
                async with lifespan(server):
                    yield
            else:
                yield
        finally:
            close = getattr(store, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await result

    middleware = [PolicyMiddleware(config)]
    if provider:
        middleware.insert(0, AuthMiddleware(auth=authorize("read", config)))
    server = FastMCP(config.name, version=config.version, instructions=instructions,
                     auth=provider, lifespan=lifetime, middleware=middleware)
    if healthcheck is not None:
        from starlette.responses import JSONResponse

        @server.custom_route("/healthz", methods=["GET"])
        async def health(_request):
            result = healthcheck()
            if inspect.isawaitable(result):
                result = await result
            return JSONResponse(result)
    return server


def create_http_app(server: FastMCP, config: RuntimeConfig):
    hosts = list(config.allowed_hosts)
    public_host = urlsplit(config.public_base_url).hostname
    if public_host and public_host not in hosts:
        hosts.insert(0, public_host)
    return server.http_app(path="/mcp", transport="streamable-http", stateless_http=True,
                           json_response=False, allowed_hosts=hosts,
                           allowed_origins=config.allowed_origins)
