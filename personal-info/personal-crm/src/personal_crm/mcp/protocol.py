"""2026 MCP 工具请求适配；鉴权和工具执行仍由固定 SDK 处理。

复用 mcp-platform 0.1.6 的协议转换，不引入 Events、队列或后台状态。
"""

import base64
import json
from types import SimpleNamespace

from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from mcp_platform import authorize
from starlette.requests import Request
from starlette.responses import JSONResponse

PROTOCOL_VERSION = "2026-07-28"
LEGACY_VERSION = "2025-11-25"
MAX_BODY_BYTES = 8 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


class ProtocolError(ValueError):
    def __init__(self, code, message, *, status=400):
        super().__init__(message)
        self.code, self.status = code, status


def attach(app, server, config):
    route = next(r for r in app.routes if getattr(r, "path", None) == "/mcp")
    if config.development_no_auth:
        route.app = ToolsEndpoint(route.app, config, server)
    else:
        if not isinstance(route.app, RequireAuthMiddleware):
            raise ValueError("MCP authentication guard required")
        route.app.app = ToolsEndpoint(route.app.app, config, server)
    return app


class ToolsEndpoint:
    def __init__(self, delegate, config, server):
        self.delegate, self.config, self.server = delegate, config, server

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST":
            return await self.delegate(scope, receive, send)
        request = Request(scope, receive)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BODY_BYTES:
                return await JSONResponse({"error": "request_too_large"}, status_code=413)(
                    scope, receive, send
                )
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(raw), "more_body": False}
            return await receive()

        try:
            message = json.loads(raw)
        except (ValueError, UnicodeError):
            return await self.delegate(scope, replay, send)
        if not isinstance(message, dict):
            return await self.delegate(scope, replay, send)
        method, params = message.get("method"), message.get("params", {})
        meta = params.get("_meta", {}) if isinstance(params, dict) else {}
        version = (
            meta.get("io.modelcontextprotocol/protocolVersion") if isinstance(meta, dict) else None
        )
        header = request.headers.get("mcp-protocol-version")
        if version is None and header != PROTOCOL_VERSION and method != "server/discover":
            return await self.delegate(scope, replay, send)
        try:
            check = authorize("read", self.config)
            token = getattr(scope.get("user"), "access_token", None)
            if check is not None and (token is None or not check(SimpleNamespace(token=token))):
                raise ProtocolError(-32001, "Access denied", status=403)
            if (
                message.get("jsonrpc") != "2.0"
                or message.get("id") is None
                or isinstance(message["id"], bool)
            ):
                raise ProtocolError(-32600, "Invalid JSON-RPC request")
            if (
                version != PROTOCOL_VERSION
                or header != version
                or request.headers.get("mcp-method") != method
            ):
                raise ProtocolError(-32020, "Missing or mismatched MCP headers")
            if not isinstance(meta.get("io.modelcontextprotocol/clientCapabilities"), dict):
                raise ProtocolError(-32602, "Client capabilities required")
            if "inputResponses" in params or "requestState" in params:
                raise ProtocolError(-32602, "Multi-round input unsupported")
            if method == "server/discover":
                result = {
                    "supportedVersions": [PROTOCOL_VERSION, LEGACY_VERSION],
                    "capabilities": {"tools": {}},
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": self.config.name,
                            "version": self.config.version,
                        }
                    },
                    "ttlMs": 0,
                    "cacheScope": "private",
                    "resultType": "complete",
                    "instructions": self.server.instructions,
                }
                return await JSONResponse(
                    {"jsonrpc": "2.0", "id": message["id"], "result": result}
                )(scope, receive, send)
            if method == "tools/call":
                name = request.headers.get("mcp-name", "")
                if name.startswith("=?base64?") and name.endswith("?="):
                    name = base64.b64decode(name[9:-2], validate=True).decode()
                if name != params.get("name"):
                    raise ProtocolError(-32020, "Mismatched MCP tool name")
            if method not in {"tools/list", "tools/call"}:
                raise ProtocolError(-32601, "Method not found", status=404)
            return await self._legacy_tools(scope, replay, send, message)
        except (ValueError, UnicodeError) as exc:
            code, status = (
                (exc.code, exc.status) if isinstance(exc, ProtocolError) else (-32602, 400)
            )
            return await JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {
                        "code": code,
                        "message": str(exc)
                        if isinstance(exc, ProtocolError)
                        else "Invalid request",
                    },
                },
                status_code=status,
            )(scope, receive, send)

    async def _legacy_tools(self, scope, receive, send, request_message):
        # Execute through the existing SDK: its token context, tool-specific auth,
        # policy timeout, output limits and audit all remain in force.
        headers = [
            (k, v)
            for k, v in scope["headers"]
            if k.lower() not in (b"mcp-protocol-version", b"mcp-session-id", b"last-event-id")
        ]
        headers.append((b"mcp-protocol-version", LEGACY_VERSION.encode()))
        adapted = dict(scope, headers=headers)
        buffer = bytearray()
        content_type = ""

        def complete(payload):
            value = json.loads(payload)
            if isinstance(value, dict) and isinstance(value.get("result"), dict):
                value["result"]["resultType"] = "complete"
                if request_message["method"] == "tools/list":
                    value["result"].update(ttlMs=0, cacheScope="private")
            return _json(value)

        async def adapt_send(message):
            nonlocal content_type
            if message["type"] == "http.response.start":
                content_type = dict(message.get("headers", [])).get(b"content-type", b"").decode()
                new_headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in (b"content-length", b"mcp-session-id")
                ]
                await send(dict(message, headers=new_headers))
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            buffer.extend(message.get("body", b""))
            if len(buffer) > max(MAX_BODY_BYTES * 2, self.config.max_output_bytes * 2):
                raise ProtocolError(-32000, "Tool response exceeded adapter limit", status=502)
            if "text/event-stream" in content_type:
                normalized = bytes(buffer).replace(b"\r\n", b"\n")
                parts = normalized.split(b"\n\n")
                buffer[:] = parts.pop()
                for part in parts:
                    lines = part.split(b"\n")
                    data = b"\n".join(
                        line[5:].lstrip(b" ") for line in lines if line.startswith(b"data:")
                    )
                    if data:
                        value = json.loads(data)
                        # The adapter exposes no sampling/elicitation capabilities.
                        if "method" in value and "id" in value:
                            raise ProtocolError(
                                -32000, "Legacy server callbacks are unsupported", status=502
                            )
                        if (
                            value.get("method") == "notifications/message"
                            and "io.modelcontextprotocol/logLevel"
                            not in request_message["params"]["_meta"]
                        ):
                            continue
                        other = [line for line in lines if not line.startswith(b"data:")]
                        part = b"\n".join(other + [b"data: " + complete(data)])
                    await send(
                        {"type": "http.response.body", "body": part + b"\n\n", "more_body": True}
                    )
                if not message.get("more_body", False):
                    await send(
                        {"type": "http.response.body", "body": bytes(buffer), "more_body": False}
                    )
                    buffer.clear()
            elif not message.get("more_body", False):
                payload = bytes(buffer)
                if "application/json" in content_type:
                    payload = complete(payload)
                await send(dict(message, body=payload))
                buffer.clear()

        await self.delegate(adapted, receive, adapt_send)
