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


def create_mcp(service: Any, settings: Any) -> FastMCP:
    """创建完整 MCP 服务；本地无 OAuth 配置时便于离线测试。"""

    runtime = _runtime(settings)
    server = create_server(
        runtime,
        instructions="可读取指定日期的微信聊天原文，不代发消息；修改工具会返回 before/after。",
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

    @server.tool(auth=write_auth)
    def upsert_person(
        display_name: str,
        person_id: str | None = None,
        aliases: list[str] | None = None,
        pronouns: str | None = None,
        contact_methods: dict[str, list[str]] | None = None,
        status: str = "active",
        relationship_to_me: str | None = None,
        organizations: list[dict[str, Any]] | None = None,
        tags: list[str] | None = None,
        contact_interval_days: int | None = None,
        profile_notes: str | None = None,
    ) -> dict[str, Any]:
        """创建或更新人物，并返回修改前后。"""

        entity, before = service.upsert_person(
            person_id=person_id,
            display_name=display_name,
            aliases=aliases,
            pronouns=pronouns,
            contact_methods=contact_methods,
            status=status,
            relationship_to_me=relationship_to_me,
            organizations=organizations,
            tags=tags,
            contact_interval_days=contact_interval_days,
            profile_notes=profile_notes,
        )
        return {"entity_id": entity.id, "before": before or None, "after": _row(service, entity)}

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

    @server.tool(auth=write_auth)
    def record_interaction(
        person_id: str,
        occurred_at: datetime,
        direction: str,
        summary: str,
        interaction_type: str = "message",
        channel: str = "manual",
        source_type: str = "manual",
        source_reference: str | None = None,
        source_event_key: str | None = None,
    ) -> dict[str, Any]:
        """记录互动摘要，并返回幂等状态和自动完成提醒数。"""

        entity, created, completed_count = service.record_interaction(
            person_id=person_id,
            occurred_at=occurred_at,
            direction=direction,
            summary=summary,
            interaction_type=interaction_type,
            channel=channel,
            source_type=source_type,
            source_reference=source_reference,
            source_event_key=source_event_key,
        )
        return {
            "entity_id": entity.id,
            "before": None,
            "after": _row(service, entity),
            "created": created,
            "completed_reminders": completed_count,
        }

    @server.tool(auth=read_auth)
    def list_facts(person_id: str | None = None, limit: int = 100):
        """列出自动确认事实及其生命周期。"""

        return [_row(service, item) for item in service.repo.list_facts(person_id, limit)]

    @server.tool(auth=write_auth)
    def add_fact(
        person_id: str,
        fact_type: str,
        content: str,
        observed_at: datetime | None = None,
        confidence: float | None = None,
        source_interaction_id: str | None = None,
    ) -> dict[str, Any]:
        """自动确认事实并保留来源。"""

        entity, created = service.record_fact(
            person_id=person_id,
            fact_type=fact_type,
            content=content,
            observed_at=observed_at,
            confidence=confidence,
            source_interaction_id=source_interaction_id,
        )
        return {
            "entity_id": entity.id,
            "before": None,
            "after": _row(service, entity),
            "created": created,
        }

    @server.tool(auth=write_auth)
    def update_fact_status(fact_id: str, status: str) -> dict[str, Any]:
        """更新事实生命周期。"""

        entity, before = service.update_fact_status(fact_id, status)
        return {"entity_id": entity.id, "before": before, "after": _row(service, entity)}

    @server.tool(auth=read_auth)
    def list_reminders(person_id: str | None = None, status: str | None = None, limit: int = 100):
        """列出提醒。"""

        return [
            _row(service, item) for item in service.repo.list_reminders(person_id, status, limit)
        ]

    @server.tool(auth=write_auth)
    def create_reminder(
        person_id: str,
        due_at: datetime,
        reason: str,
        reminder_type: str = "follow_up",
        suggested_message: str | None = None,
        recurrence_rule: str | None = None,
    ) -> dict[str, Any]:
        """创建提醒。"""

        entity = service.create_reminder(
            person_id=person_id,
            due_at=due_at,
            reason=reason,
            reminder_type=reminder_type,
            suggested_message=suggested_message,
            recurrence_rule=recurrence_rule,
        )
        return {"entity_id": entity.id, "before": None, "after": _row(service, entity)}

    def change_reminder(reminder_id: str, status: str, due_at: datetime | None = None):
        """执行提醒状态变化并返回前后快照。"""

        entity, before = service.update_reminder_status(reminder_id, status, due_at=due_at)
        return {"entity_id": entity.id, "before": before, "after": _row(service, entity)}

    @server.tool(auth=write_auth)
    def complete_reminder(reminder_id: str):
        """手工完成提醒。"""

        return change_reminder(reminder_id, "completed")

    @server.tool(auth=write_auth)
    def snooze_reminder(reminder_id: str, due_at: datetime):
        """把提醒推迟到新时间。"""

        return change_reminder(reminder_id, "snoozed", due_at)

    @server.tool(auth=write_auth)
    def skip_reminder(reminder_id: str):
        """跳过提醒并保留绩效记录。"""

        return change_reminder(reminder_id, "skipped")

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

    return server


def http_app(service: Any, settings: Any):
    """公共基座提供无状态 HTTP、发现路由及生命周期。"""

    return create_http_app(create_mcp(service, settings), _runtime(settings))
