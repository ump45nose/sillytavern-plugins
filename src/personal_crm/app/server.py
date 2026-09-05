"""FastAPI、Webhook 与 Streamable HTTP MCP 的统一进程入口。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from personal_crm.core import CrmService
from personal_crm.mcp import http_app
from personal_crm.reminders import ReminderService
from personal_crm.storage import CrmRepository
from personal_crm.webhook import create_router

from .settings import Settings


def create_app(settings: Settings | None = None, repository=None) -> FastAPI:
    """装配健康检查、Webhook 和 MCP；具体模块只依赖公开服务。"""

    runtime = settings or Settings()
    repo = repository or CrmRepository(runtime.database_url)
    service = CrmService(repo)
    reminder_service = ReminderService(repo)
    mcp_application = http_app(service, runtime)

    async def run_reminder_scheduler() -> None:
        """定期补齐本周提醒；持久化周预算保证重复执行不会超额。"""

        while True:
            try:
                reminder_service.generate_weekly()
            except Exception:
                # 后台生成失败不能拖垮查询服务，日志只记录异常而不包含人物内容。
                logging.getLogger(__name__).exception("每周提醒生成失败")
            await asyncio.sleep(max(runtime.reminder_poll_seconds, 60))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """把 FastMCP 的生命周期纳入主 ASGI 应用。"""

        del app
        scheduler_task = None
        async with mcp_application.lifespan(mcp_application):
            if runtime.reminder_scheduler_enabled:
                scheduler_task = asyncio.create_task(run_reminder_scheduler())
            try:
                yield
            finally:
                if scheduler_task is not None:
                    scheduler_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await scheduler_task

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
        """直接返回无后缀资源元数据，兼容 ChatGPT 等严格发现客户端。"""

        if not runtime.oauth_enabled:
            raise HTTPException(status_code=404, detail="OAuth is not configured")
        base_url = runtime.public_base_url.rstrip("/")
        # 保留 FastMCP 权威端点的字段语义，避免客户端必须跟随相对重定向。
        return JSONResponse(
            {
                "resource": f"{base_url}/mcp",
                "authorization_servers": [f"{base_url}/"],
                "scopes_supported": ["read:user", "user:email"],
                "bearer_methods_supported": ["header"],
            }
        )

    # 根挂载必须最后注册，让 FastMCP 同时暴露 /mcp 与 OAuth discovery 路由。
    app.mount("/", mcp_application)
    return app


def main() -> None:
    """按环境变量启动 Uvicorn。"""

    import uvicorn

    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
