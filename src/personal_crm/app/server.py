"""FastAPI、Webhook 与 Streamable HTTP MCP 的统一进程入口。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from personal_crm.core import CrmService
from personal_crm.mcp import http_app
from personal_crm.storage import CrmRepository
from personal_crm.webhook import create_router

from .settings import Settings


def create_app(settings: Settings | None = None, repository=None) -> FastAPI:
    """装配健康检查、Webhook 和 MCP；具体模块只依赖公开服务。"""

    runtime = settings or Settings()
    repo = repository or CrmRepository(runtime.database_url)
    service = CrmService(repo)
    mcp_application = http_app(service, runtime)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """把 FastMCP 的生命周期纳入主 ASGI 应用。"""

        del app
        async with mcp_application.lifespan(mcp_application):
            yield

    app = FastAPI(title="Personal CRM", lifespan=lifespan)
    app.state.repository = repo
    app.state.crm_service = service
    app.include_router(create_router(repo, runtime.wechat_webhook_secret))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """同时验证进程和 SQLite 完整性。"""

        return {"status": "ok", "database": repo.integrity_check()}

    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    def oauth_protected_resource():
        """兼容无资源路径后缀的 OAuth 发现客户端。"""

        if not runtime.oauth_enabled:
            raise HTTPException(status_code=404, detail="OAuth is not configured")
        # FastMCP 按 RFC 9728 为 /mcp 资源生成带路径后缀的权威元数据地址。
        return RedirectResponse("/.well-known/oauth-protected-resource/mcp", status_code=307)

    # 根挂载必须最后注册，让 FastMCP 同时暴露 /mcp 与 OAuth discovery 路由。
    app.mount("/", mcp_application)
    return app


def main() -> None:
    """按环境变量启动 Uvicorn。"""

    import uvicorn

    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
