"""Three domain tools; transport and client integration stay outside the core."""
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
    server = MCPServer('media-download', version='0.1.2',
        instructions='查询电影或剧集资源，并在一次 download_media 调用中选源和提交下载。'
        '优先使用对话中已有的 TMDB/IMDb ID。pending 是等待核实，不是下载成功；'
        '用 get_download_status 续查，勿换 request_id 重复提交。')

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def search_resources(request: AcquisitionRequest | None = None,
                               session_id: str | None = None, source_id: str | None = None) -> dict[str, Any]:
        """查询 M-Team、Mini4K，返回候选引用、字幕证据及逐站状态，不下载种子。

        首次提供 request；身份不唯一时返回 choices，用其中 ID 重查。后续仅提供
        session_id 续查，额外提供 source_id 读取该站下一页。候选引用有效 15 分钟。
        身份识别无结果或不可用时，按 title+year 直接查询；identity_status=unverified
        表示尚未核实媒体身份，这类候选需提供媒体 ID 重新搜索后才能下载。
        """
        if (request is None) == (session_id is None):
            raise ValueError('request 与 session_id 必须且只能提供一个')
        if source_id and not session_id:
            raise ValueError('分页需要 session_id')
        return await anyio.to_thread.run_sync(lambda: bridge.search(asdict(request)) if request else
            bridge.more(session_id, source_id) if source_id else bridge.search_status(session_id),
            abandon_on_cancel=True)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True))
    async def download_media(request: AcquisitionRequest) -> dict[str, Any]:
        """一次完成媒体识别、检索、按策略选源、文件核验和下载提交（写操作）。

        用 candidate_id 下载指定资源（通过范围和安全校验，忽略自动选源偏好），或提供 tmdb_id+media_type、imdb_id、
        title+可选 year 自动选源。policy 默认 quality，另有 subtitle、balanced。
        电视剧 scope 默认 season（season 默认 1）；episode 必须给季号和集号；
        series 只接受已完结全剧的单一完整 BT 资源，不拆季。无媒体库去重门槛。
        等待受理最多 120 秒；只有 submitted/已确认回执代表接收，pending 需续查。
        重试原调用时保留 request_id，禁止在提交结果未知时创建新请求。
        """
        return await anyio.to_thread.run_sync(lambda: bridge.download(asdict(request)), abandon_on_cancel=True)

    @server.tool(structured_output=True, annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    async def get_download_status(task_id: str) -> dict[str, Any]:
        """按下载回执中的 task_id 读取接收状态及下载器进度；不检查媒体入库。"""
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
