"""Personal CRM 的 FastMCP 工具、资源与 Authelia OIDC 装配。"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp import FastMCP
from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server

from personal_crm.core.domain import ensure_utc, utcnow
from personal_crm.metrics import weekly_metrics


def _row(service, entity: Any | None) -> dict[str, Any] | None:
    """把 ORM 实体投影为稳定 JSON 字典。"""

    return service.repo.to_dict(entity)


def _runtime(settings: Any) -> RuntimeConfig:
    """适配原有 CRM 环境变量，保留 OAuth 状态格式与公开地址。"""

    return RuntimeConfig(
        name="personal-crm", host=settings.host, port=settings.port,
        development_no_auth=settings.mcp_development_no_auth,
        public_base_url=settings.public_base_url,
        oidc_discovery_url=settings.oidc_discovery_url,
        oidc_client_id=settings.oidc_client_id, oidc_client_secret=settings.oidc_client_secret,
        jwt_signing_key=settings.oauth_jwt_signing_key,
        storage_encryption_key=settings.oauth_storage_encryption_key,
        storage_path=settings.oauth_storage_path, storage_salt="personal-crm-oauth-v1",
        authorized_usernames=settings.authorized_usernames,
        read_only_usernames=settings.read_only_usernames,
        client_redirect_uris=settings.client_redirect_uris,
        allowed_hosts=["localhost", "127.0.0.1", "personal-crm"],
        allowed_origins=["https://chatgpt.com", "https://claude.ai", "https://claude.com",
                         "https://grok.com", "https://x.ai", "https://x.com"],
        proxy_sni_compatibility=settings.mcp_proxy_sni_compatibility,
        requests_per_minute=0, tool_timeout_seconds=0, max_output_bytes=0,
    )


def _auth_check(settings: Any, *, write: bool):
    return authorize("write" if write else "read", _runtime(settings))


def create_mcp(service: Any, settings: Any, *, chat_reports=None,
               daily_reviews=None, daily_review_reports=None, hub_store=None) -> FastMCP:
    """创建完整 MCP 服务；本地无 OAuth 配置时便于离线测试。"""

    runtime = _runtime(settings)
    server = create_server(
        runtime,
        instructions=("可读取指定日期的微信聊天原文，以及已同步 Codex Skylight 摘要。"
                      "Skylight 默认查询北京时间今天；长正文可续读。"
                      "每日事件提供冻结快照的读取参数。不代发消息；"
                      "仅采集归档与只读查询，不执行提醒或其他业务处理。"),
    )
    read_auth = _auth_check(settings, write=False)
    write_auth = _auth_check(settings, write=True)

    @server.tool(auth=read_auth)
    def search_people(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
        """搜索姓名、别名、联系方式和标签。"""

        return [_row(service, item) for item in service.search_people(query, limit)]

    @server.tool(auth=read_auth)
    def get_person(person_id: str) -> dict[str, Any] | None:
        """读取人物。"""

        return _row(service, service.get_person(person_id))


    @server.tool(auth=read_auth)
    def list_interactions(person_id: str | None = None, limit: int = 100):
        """按时间倒序列出互动。"""

        return [_row(service, item) for item in service.repo.list_interactions(person_id, limit)]

    @server.tool(auth=read_auth)
    def get_daily_chat_records(
        day: str, timezone: str = "Asia/Shanghai", offset: int = 0, limit: int = 200,
    ) -> dict[str, Any]:
        """分页返回当天微信聊天原文；不在 CRM 内压缩或生成摘要。"""

        try:
            business_day = datetime.strptime(day, "%Y-%m-%d").date()
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("day 或 timezone 无效") from error
        start = datetime.combine(business_day, time.min, zone)
        rows = service.repo.daily_chat_records(start, start + timedelta(days=1), offset, limit)
        return {"date": day, "timezone": timezone, "offset": offset,
                "limit": limit, "records": rows,
                "next_offset": offset + len(rows) if len(rows) == limit else None}

    @server.tool(auth=read_auth)
    def get_daily_summary(day: str, timezone: str = "Asia/Shanghai") -> dict[str, Any]:
        """返回指定业务日的紧凑关系变化；不泄露互动、事实或提醒正文。"""

        try:
            business_day = datetime.strptime(day, "%Y-%m-%d").date()
            zone = ZoneInfo(timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("day 或 timezone 无效") from error
        # 业务日窗口先在用户时区构造，再由仓储统一转换成 UTC 查询。
        start = datetime.combine(business_day, time.min, zone)
        end = start + timedelta(days=1)
        summary = service.repo.daily_summary(start, end)
        return {"date": day, "timezone": timezone, **summary}


    @server.tool(auth=read_auth)
    def list_facts(person_id: str | None = None, limit: int = 100):
        """列出自动确认事实及其生命周期。"""

        return [_row(service, item) for item in service.repo.list_facts(person_id, limit)]



    @server.tool(auth=read_auth)
    def list_reminders(person_id: str | None = None, status: str | None = None, limit: int = 100):
        """列出提醒。"""

        return [
            _row(service, item) for item in service.repo.list_reminders(person_id, status, limit)
        ]


    def change_reminder(reminder_id: str, status: str, due_at: datetime | None = None):
        """执行提醒状态变化并返回前后快照。"""

        entity, before = service.update_reminder_status(reminder_id, status, due_at=due_at)
        return {"entity_id": entity.id, "before": before, "after": _row(service, entity)}




    @server.tool(auth=read_auth)
    def get_weekly_metrics(week_start: datetime | None = None):
        """返回指定周的提醒绩效。"""

        start = ensure_utc(week_start or utcnow())
        start = (start - timedelta(days=start.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return weekly_metrics(service.repo, start)

    @server.resource("crm://people/{person_id}", auth=read_auth)
    def person_resource(person_id: str):
        """将人物作为 MCP 资源暴露。"""

        return get_person(person_id)

    @server.resource("crm://weekly-metrics", auth=read_auth)
    def metrics_resource():
        """将本周绩效作为 MCP 资源暴露。"""

        return get_weekly_metrics()

    if chat_reports is not None:
        from personal_crm.events import register_chat_event_tools

        register_chat_event_tools(server, chat_reports, auth=read_auth)
    if daily_reviews is None:
        from personal_crm.daily_review import DailyReviewService

        daily_reviews = DailyReviewService(
            skylight_path=settings.codex_skylight_path,
        )
    from personal_crm.daily_review import register_daily_review_tools

    register_daily_review_tools(server, daily_reviews, auth=read_auth)
    if daily_review_reports:
        from personal_crm.daily_review_events import register_daily_review_event_tools

        register_daily_review_event_tools(server, daily_review_reports, auth=read_auth)
    if hub_store is not None:
        from personal_data_hub.mcp import register_tools
        register_tools(server, hub_store, read_auth, chat_reports=chat_reports)
    return server


def http_app(service: Any, settings: Any, *, events=None, chat_reports=None,
             daily_reviews=None, daily_review_reports=None, hub_store=None):
    """公共基座提供 HTTP、发现路由及经过同一认证的事件协议。"""

    server = create_mcp(service, settings, chat_reports=chat_reports,
                        daily_reviews=daily_reviews, daily_review_reports=daily_review_reports, hub_store=hub_store)
    config = _runtime(settings)
    if events is not None:
        return create_http_app(server, config, events=events)
    return create_http_app(server, config)
