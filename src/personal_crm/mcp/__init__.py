"""Personal CRM 的 FastMCP 工具、资源与 GitHub OAuth 装配。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.providers.github import GitHubProvider

from personal_crm.core.domain import ensure_utc, utcnow
from personal_crm.metrics import weekly_metrics


def _row(service, entity: Any | None) -> dict[str, Any] | None:
    """把 ORM 实体投影为稳定 JSON 字典。"""

    return service.repo.to_dict(entity)


def _auth_check(settings: Any, *, write: bool):
    """按 GitHub 数字用户 ID 映射 CRM 读写权限。"""

    if not getattr(settings, "oauth_enabled", False):
        return None

    def check(context: AuthContext) -> bool:
        """拒绝非白名单用户，并阻止只读用户调用修改工具。"""

        token = context.token
        if token is None:
            return False
        user_id = str(token.claims.get("sub") or token.client_id)
        if user_id not in settings.allowed_user_ids:
            return False
        return not (write and user_id in settings.read_only_user_ids)

    return check


def _provider(settings: Any) -> GitHubProvider | None:
    """在生产配置完整时创建 FastMCP GitHub OAuth Provider。"""

    if not getattr(settings, "oauth_enabled", False):
        return None
    if not settings.allowed_user_ids:
        raise ValueError("GITHUB_ALLOWED_USER_IDS is required when OAuth is enabled")
    base_url = settings.public_base_url.rstrip("/")
    return GitHubProvider(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        base_url=base_url,
        issuer_url=base_url,
        required_scopes=["read:user", "user:email"],
        allowed_client_redirect_uris=settings.client_redirect_uris,
        jwt_signing_key=settings.oauth_jwt_signing_key or None,
        require_authorization_consent=True,
        enable_cimd=True,
    )


def create_mcp(service: Any, settings: Any) -> FastMCP:
    """创建完整 MCP 服务；本地无 OAuth 配置时便于离线测试。"""

    server = FastMCP(
        "personal-crm",
        instructions="只读微信摘要，不代发消息；修改工具会返回 before/after。",
        auth=_provider(settings),
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
    """返回仅使用 Streamable HTTP 的 ASGI 应用。"""

    return create_mcp(service, settings).http_app(path="/mcp", transport="streamable-http")
