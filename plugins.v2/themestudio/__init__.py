from typing import Any
import re
import httpx
from fastapi import HTTPException, Request, Depends
from fastapi.responses import Response, StreamingResponse
from anyio import CancelScope
from app.plugins import _PluginBase
from app.core.security import verify_token, set_or_refresh_resource_token_cookie
from app.schemas import TokenPayload
from app.db.user_oper import get_current_active_superuser_async

class WorkerAudioResponse(StreamingResponse):
    """Own the upstream even if the downstream never starts consuming its body."""
    def __init__(self, response, client):
        self.upstream, self.client = response, client
        headers = {"Cache-Control": "no-store"}
        if response.headers.get("content-length"):
            headers["Content-Length"] = response.headers["content-length"]
        super().__init__(response.aiter_bytes(256 * 1024), status_code=response.status_code,
                         media_type=response.headers.get("content-type", "audio/mpeg"), headers=headers)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # ASGI disconnect can cancel the response before its iterator starts.
            with CancelScope(shield=True):
                try:
                    await self.upstream.aclose()
                finally:
                    await self.client.aclose()


class ThemeStudio(_PluginBase):
    plugin_name = "主题曲管理"
    plugin_desc = "自动检索、智能提取、试听裁剪与人工完成锁定"
    plugin_icon = "https://raw.githubusercontent.com/ump45nose/emby-theme-worker/main/moviepilot/icon.svg"
    plugin_version = "0.3.0"
    plugin_author = "ump45nose"
    author_url = "https://github.com/ump45nose"
    plugin_config_prefix = "themestudio_"
    plugin_order = 60
    auth_level = 1

    def init_plugin(self, config=None):
        self._enabled = (config or {}).get("enabled", True)

    def get_state(self):
        return self._enabled

    def get_api(self):
        return [{"path": "/session", "endpoint": self.session, "methods": ["GET"], "auth": "bear", "summary": "刷新已认证客户端的宿主资源 Cookie"},
                {"path": "/studio/{path:path}", "endpoint": self.proxy, "methods": ["GET", "POST"], "auth": "bear", "summary": "Theme Worker 私有控制接口"}]

    async def session(self, request: Request, response: Response, payload: TokenPayload = Depends(verify_token)):
        # Uses the host's verified identity and cookie implementation, not a
        # separate credential or anonymous resource endpoint.
        set_or_refresh_resource_token_cookie(request, response, payload)
        return {"authenticated": True}

    async def proxy(self, path: str, request: Request, admin=Depends(get_current_active_superuser_async)):
        if not self._enabled:
            raise HTTPException(503, "插件已停用")
        if not re.fullmatch(r"(?:media|jobs|status|source|lock|pause|feedback|retry|(?:audio|source-audio|current|diagnostics|upload)/[a-zA-Z0-9_-]{1,80})", path):
            raise HTTPException(404, "未知操作")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 32*1024*1024:
                raise HTTPException(413, "上传最大 32 MiB")
        try:
            transport = httpx.AsyncHTTPTransport(uds="/run/theme-worker/control.sock")
            if request.method == "GET" and path.split("/", 1)[0] in {"audio", "source-audio", "current"}:
                client = httpx.AsyncClient(transport=transport, timeout=60)
                try:
                    response = await client.send(client.build_request("GET", "http://worker/"+path), stream=True)
                except BaseException:
                    await client.aclose()
                    raise
                return WorkerAudioResponse(response, client)
            async with httpx.AsyncClient(transport=transport, timeout=60) as client:
                response = await client.request(request.method, "http://worker/"+path, content=bytes(body), headers={"Content-Type": request.headers.get("content-type", "application/json")})
            return Response(response.content, status_code=response.status_code, media_type=response.headers.get("content-type", "application/json"), headers={"Cache-Control": "no-store"})
        except httpx.HTTPError:
            raise HTTPException(503, "Worker 不可用，请检查共享 socket")

    @staticmethod
    def get_render_mode():
        return "vue", "dist"

    def get_form(self):
        return None, {"enabled": True}

    def get_page(self):
        return None

    def get_command(self):
        return []

    def get_service(self):
        return []

    def get_sidebar_nav(self):
        return [{"title": "主题曲管理", "icon": "mdi-music", "nav_key": "main", "section": "organize", "permission": "manage"}]

    def stop_service(self):
        pass
