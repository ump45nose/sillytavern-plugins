"""Four domain tools; transport and client integration stay outside the core."""
import argparse
from dataclasses import asdict
import hmac
from typing import Any

import anyio
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings

from media_capabilities.acquisition.client import BridgeClient, ConnectionSettings, read_secret
from media_capabilities.acquisition.models import AcquisitionRequest


def create_server(bridge):
    server = MCPServer('media-download', version='0.1.4',
        instructions='检索媒体信息、提交下载并查询进度。')

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def search_resources(request: AcquisitionRequest | None = None,
                               session_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
        """检索服务器上的媒体资源，返回候选引用、字幕信息及查询状态。"""
        if (request is None) == (session_id is None):
            raise ValueError('request 与 session_id 必须且只能提供一个')
        if source_id and not session_id:
            raise ValueError('分页需要 session_id')
        return await anyio.to_thread.run_sync(lambda: bridge.search(asdict(request)) if request else
            bridge.more(session_id, source_id) if source_id else bridge.search_status(session_id),
            abandon_on_cancel=True)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    async def download_media(request: AcquisitionRequest) -> dict[str, Any]:
        """提交媒体下载任务。使用 candidate_id 指定候选，或根据片名、TMDB/IMDb 标识及偏好检索、选择资源并提交到下载器。"""
        return await submit_download(request)

    async def submit_download(request):
        return await anyio.to_thread.run_sync(lambda: bridge.download(asdict(request)), abandon_on_cancel=True)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    async def check_media(request: AcquisitionRequest) -> dict[str, Any]:
        """查询媒体信息。使用 candidate_id 指定候选，或根据片名、TMDB/IMDb 标识及偏好检索、选择资源。"""
        return await submit_download(request)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def get_download_status(task_id: str) -> dict[str, Any]:
        """查询指定任务的下载状态。"""
        return await anyio.to_thread.run_sync(lambda: bridge.status(task_id), abandon_on_cancel=True)

    return server


class TokenGuard:
    def __init__(self, app, token_file):
        read_secret(token_file)
        self.app, self.token_file = app, token_file

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            headers = dict(scope.get('headers', []))
            supplied = headers.get(b'authorization', b'').decode('utf-8', 'replace')
            expected = 'Bearer ' + read_secret(self.token_file)
            if not hmac.compare_digest(supplied, expected):
                await send({'type': 'http.response.start', 'status': 401,
                            'headers': [(b'content-type', b'application/json')]})
                await send({'type': 'http.response.body', 'body': b'{"error":"unauthorized"}'})
                return
        await self.app(scope, receive, send)


def create_http_app(server, settings):
    if not settings.access_token_file:
        raise ValueError('HTTP MCP 需要 access_token_file')
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
        allowed_hosts=[v for h in settings.public_hosts for v in (h, h + ':*')],
        allowed_origins=[scheme + '://' + v for h in settings.public_hosts
                         for v in (h, h + ':*') for scheme in ('http', 'https')])
    app = server.streamable_http_app(stateless_http=True, transport_security=security,
                                     host=settings.host)
    return TokenGuard(app, settings.access_token_file)


def main():
    parser = argparse.ArgumentParser(description='通用电影与剧集下载 MCP')
    parser.add_argument('--config', required=True)
    parser.add_argument('--transport', choices=('stdio', 'streamable-http'), default='stdio')
    args = parser.parse_args()
    settings = ConnectionSettings.load(args.config)
    bridge = BridgeClient(settings)
    server = create_server(bridge)
    try:
        if args.transport == 'stdio':
            server.run('stdio')
        else:
            import uvicorn
            uvicorn.run(create_http_app(server, settings), host=settings.host, port=settings.port)
    finally:
        bridge.close()
