"""Media Download 的 OAuth 入口；保留现有业务服务和 Bearer 客户端。"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import Middleware

from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server

TOOL_PERMISSIONS = {
    "search_resources": "read",
    "download_media": "write",
    "check_media": "write",
    "get_download_status": "read",
}


def read_secret(path: Path) -> str:
    if not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("后端令牌必须是独立的 600 权限文件")
    token = path.read_text().strip()
    if not token or "\n" in token or "\r" in token:
        raise ValueError("后端令牌文件无效")
    return token


class BackendAuth(httpx.Auth):
    def __init__(self, token_file):
        self.token_file = token_file

    def auth_flow(self, request):
        request.headers["Authorization"] = "Bearer " + read_secret(self.token_file)
        yield request


class ToolPermissions(Middleware):
    def __init__(self, config):
        self.config = config

    async def on_call_tool(self, context, call_next):
        permission = TOOL_PERMISSIONS.get(context.message.name)
        if permission is None:
            raise ToolError("unsupported_tool: 未登记的后端工具")
        check = authorize(permission, self.config)
        if check and not check(SimpleNamespace(token=get_access_token())):
            raise ToolError("permission_denied: 当前账号无此工具权限")
        return await call_next(context)


def build_gateway(config, *, backend_url, token_file, backend_host, legacy_username=""):
    read_secret(token_file)
    parsed = httpx.URL(backend_url)
    if parsed.scheme != "http" or parsed.host != "127.0.0.1":
        raise ValueError("本入口的业务后端必须是本机回环 HTTP 服务")
    if legacy_username and legacy_username not in config.authorized_usernames:
        raise ValueError("旧 Bearer 身份必须是已授权的账号")

    async def healthcheck():
        async with Client(transport, timeout=10) as client:
            tools = await client.list_tools()
        if {tool.name for tool in tools} != set(TOOL_PERMISSIONS):
            raise ToolError("backend_tools_changed: 后端工具清单需要核对")
        return {"status": "ok", "tools": sorted(TOOL_PERMISSIONS)}

    transport = StreamableHttpTransport(
        backend_url,
        headers={"Host": backend_host},
        auth=BackendAuth(token_file),
    )
    server = create_server(
        config, instructions="检索媒体信息、提交下载并查询进度。", healthcheck=healthcheck
    )
    server.add_middleware(ToolPermissions(config))
    server.mount(FastMCP.as_proxy(Client(transport, timeout=180)))

    if legacy_username:
        original_verify = server.auth.verify_token

        async def verify_token(token):
            if hmac.compare_digest(token.encode(), read_secret(token_file).encode()):
                # 旧文件令牌原本已拥有业务写权限；只兼容显式指定的原账号。
                return AccessToken(
                    token=token,
                    client_id="legacy-bearer",
                    scopes=["openid", "profile", "offline_access"],
                    resource=config.public_base_url,
                    subject="legacy-bearer",
                    claims={
                        "sub": "legacy-bearer",
                        "upstream_claims": {"preferred_username": legacy_username},
                    },
                )
            return await original_verify(token)

        server.auth.verify_token = verify_token
    return server


def main():
    config = RuntimeConfig.from_env("Media Download")
    config = config.model_copy(update={"tool_timeout_seconds": 180, "max_output_bytes": 0})
    server = build_gateway(
        config,
        backend_url=os.environ["MEDIA_BACKEND_URL"],
        token_file=Path(os.environ["MEDIA_BACKEND_TOKEN_FILE"]),
        backend_host=os.environ["MEDIA_BACKEND_HOST"],
        legacy_username=os.getenv("MEDIA_LEGACY_BEARER_USERNAME", ""),
    )
    uvicorn.run(create_http_app(server, config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
