"""FastAPI、Webhook 与 Streamable HTTP MCP 的统一进程入口。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from personal_crm.core import CrmService
from personal_crm.daily_review import DailyReviewService
from personal_crm.mcp import _runtime, http_app
from personal_crm.reminders import ReminderService
from personal_crm.storage import CrmRepository
from personal_crm.webhook import create_router

from .settings import Settings


def create_app(settings: Settings | None = None, repository=None, hub_store=None) -> FastAPI:
    """装配健康检查、Webhook 和 MCP；具体模块只依赖公开服务。"""

    runtime = settings or Settings()
    repo = repository or CrmRepository(runtime.database_url)
    service = CrmService(repo)
    reminder_service = ReminderService(repo)
    events, chat_reports = None, None
    daily_review_reports = {}
    daily_reviews = DailyReviewService(
        skylight_path=runtime.codex_skylight_path,
        memos_database_path=runtime.memos_database_path,
        memos_creator_id=runtime.memos_creator_id,
    )
    if hub_store is not None:
        from personal_data_hub.mcp import ArchiveDailyReviews
        daily_reviews = ArchiveDailyReviews(hub_store)
    if runtime.chat_events_enabled or runtime.daily_review_events_enabled:
        owners = []
        if runtime.chat_events_enabled:
            owners.append(runtime.chat_event_owner)
        if runtime.daily_review_events_enabled:
            owners.append(runtime.daily_review_event_owner)
        if (
            runtime.mcp_development_no_auth
            or any(owner not in runtime.authorized_usernames for owner in owners)
        ):
            raise ValueError("events require an explicitly authorized OAuth owner")
        from mcp_platform.events import EventService

        events = EventService(_runtime(runtime), storage_path=runtime.chat_event_storage_path)
    if runtime.chat_events_enabled:
        from personal_crm.events import ChatEventProducer

        chat_reports = ChatEventProducer(
            repo, events, owner=runtime.chat_event_owner,
            storage_path=runtime.chat_event_storage_path.rstrip("/") + "/chat-reports",
            timezone=runtime.chat_event_timezone, send_time=runtime.chat_event_time,
            poll_seconds=runtime.chat_event_poll_seconds,
        )
    if runtime.daily_review_events_enabled:
        if not runtime.codex_skylight_path or not runtime.memos_database_path:
            raise ValueError("daily review events require both read-only source paths")
        from personal_crm.daily_review_events import DailyReviewEventProducer

        for source in ("codex_skylight", "memos"):
            daily_review_reports[source] = DailyReviewEventProducer(
                daily_reviews, events, source=source, owner=runtime.daily_review_event_owner,
                storage_path=runtime.daily_review_event_storage_path,
                timezone=runtime.daily_review_event_timezone,
                send_time=runtime.daily_review_event_time,
                poll_seconds=runtime.daily_review_event_poll_seconds,
            )
    mcp_application = http_app(
        service, runtime, events=events, chat_reports=chat_reports,
        daily_reviews=daily_reviews, daily_review_reports=daily_review_reports, hub_store=hub_store,
    )

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
        tasks = []
        async with mcp_application.lifespan(mcp_application):
            if runtime.reminder_scheduler_enabled:
                tasks.append(asyncio.create_task(run_reminder_scheduler()))
            if chat_reports is not None:
                tasks.append(asyncio.create_task(chat_reports.serve()))
            for producer in daily_review_reports.values():
                tasks.append(asyncio.create_task(producer.serve()))
            if events is not None:
                tasks.append(asyncio.create_task(events.serve()))
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(title="Personal CRM", lifespan=lifespan)
    app.state.repository = repo
    app.state.crm_service = service
    app.include_router(create_router(repo, runtime.wechat_webhook_secret))

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """同时验证进程和 SQLite 完整性。"""

        return {"status": "ok", "database": repo.integrity_check()}

    @app.get("/personal-review", response_class=HTMLResponse, include_in_schema=False)
    def personal_review_home() -> str:
        """提供 Personal Review OAuth 的公开用途说明与隐私政策入口。"""

        # 页面不暴露内部部署信息，只解释 Google 只读数据的用途与边界。
        return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Personal Review</title></head><body><main>
<h1>Personal Review</h1>
<p>Personal Review 是个人复盘工具，仅以只读方式获取本人 Google Calendar 与 Google Tasks 的当日摘要，用于生成待人工确认的日报材料。</p>
<p>Google 数据不会公开分享、出售或用于广告；最终记录由用户确认后才进入个人账本。</p>
<nav><a href="/personal-review/privacy">隐私政策</a> · <a href="/personal-review/terms">服务条款</a></nav>
</main></body></html>"""

    @app.get("/personal-review/privacy", response_class=HTMLResponse, include_in_schema=False)
    def personal_review_privacy() -> str:
        """公开说明 Personal Review 对 Google 用户数据的访问和处理方式。"""

        return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Personal Review 隐私政策</title></head><body><main>
<h1>Personal Review 隐私政策</h1>
<p>Personal Review 仅访问授权账号的 Google Calendar 与 Google Tasks 只读数据，并只提取生成个人日报所需的当日摘要。</p>
<p>数据保存在用户自主管理的私有设备中，不出售、不用于广告，也不向第三方共享。用户可以随时在 Google 账号中撤销授权，并删除本地凭据与摘要。</p>
<p>本应用对 Google API 数据的使用遵守 Google API Services User Data Policy，包括 Limited Use 要求。</p>
<p><a href="/personal-review">返回首页</a></p>
</main></body></html>"""

    @app.get("/personal-review/terms", response_class=HTMLResponse, include_in_schema=False)
    def personal_review_terms() -> str:
        """提供个人自用场景下的简明服务条款。"""

        return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Personal Review 服务条款</title></head><body><main>
<h1>Personal Review 服务条款</h1>
<p>Personal Review 是个人自用工具，按现状提供。用户对授权账号、生成内容以及最终归档内容负责。</p>
<p>用户可随时停止使用并撤销 Google 授权。</p>
<p><a href="/personal-review">返回首页</a></p>
</main></body></html>"""

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
                "scopes_supported": ["openid", "profile", "offline_access"],
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
