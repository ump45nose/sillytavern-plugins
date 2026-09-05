"""Personal CRM 的 FastMCP 工具、资源与 Authelia OIDC 装配。"""

from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastmcp import FastMCP
from fastmcp.server.auth import AuthContext
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from personal_crm.core.domain import ensure_utc, utcnow
from personal_crm.metrics import weekly_metrics


def _row(service, entity: Any | None) -> dict[str, Any] | None:
    """把 ORM 实体投影为稳定 JSON 字典。"""

    return service.repo.to_dict(entity)


def _auth_check(settings: Any, *, write: bool):
    """按 Authelia 的 preferred_username 映射 CRM 读写权限。"""

    if not getattr(settings, "oauth_enabled", False):
        return None

    def check(context: AuthContext) -> bool:
        """拒绝非白名单用户，并阻止只读用户调用修改工具。"""

        token = context.token
        if token is None:
            return False
        claims = dict(token.claims) if isinstance(token.claims, dict) else {}
        # OIDCProxy 把上游身份放入 upstream_claims；兼容直接声明以便测试和升级。
        upstream_claims = claims.get("upstream_claims")
        if isinstance(upstream_claims, dict):
            for key, value in upstream_claims.items():
                claims.setdefault(key, value)
        username = claims.get("preferred_username")
        if not isinstance(username, str):
            return False
        authorized = any(
            hmac.compare_digest(username, candidate)
            for candidate in settings.authorized_usernames
        )
        if not authorized:
            return False
        return not (
            write
            and any(
                hmac.compare_digest(username, candidate)
                for candidate in settings.read_only_usernames
            )
        )

    return check


def _provider(settings: Any) -> tuple[OIDCProxy | None, FileTreeStore | None]:
    """在生产配置完整时创建与 SmartSearch 同构的 Authelia OIDCProxy。"""

    if not getattr(settings, "oauth_enabled", False):
        return None, None
    if not settings.authorized_usernames:
        raise ValueError("OIDC_AUTHORIZED_USERNAMES is required when OAuth is enabled")
    if len(settings.oauth_jwt_signing_key) < 32:
        raise ValueError("OAUTH_JWT_SIGNING_KEY must contain at least 32 characters")
    if len(settings.oauth_storage_encryption_key) < 32:
        raise ValueError("OAUTH_STORAGE_ENCRYPTION_KEY must contain at least 32 characters")

    base_url = settings.public_base_url.rstrip("/")
    storage_path = Path(settings.oauth_storage_path)
    storage_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_path.chmod(0o700)
    # CIMD 的 client_id 是 URL；必须清洗斜杠等文件名字符，否则写入会形成不存在的子目录。
    raw_store = FileTreeStore(
        data_directory=storage_path,
        key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(storage_path),
        collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(
            storage_path
        ),
    )
    encrypted_store = FernetEncryptionWrapper(
        raw_store,
        source_material=settings.oauth_storage_encryption_key,
        salt="personal-crm-oauth-v1",
        raise_on_decryption_error=True,
    )
    provider = OIDCProxy(
        config_url=settings.oidc_discovery_url,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        base_url=base_url,
        resource_base_url=base_url,
        issuer_url=base_url,
        redirect_path="/auth/callback",
        required_scopes=["openid", "profile", "offline_access"],
        verify_id_token=True,
        allowed_client_redirect_uris=settings.client_redirect_uris,
        client_storage=encrypted_store,
        jwt_signing_key=settings.oauth_jwt_signing_key,
        token_endpoint_auth_method="client_secret_basic",
        require_authorization_consent=True,
        enable_cimd=True,
        forward_resource=False,
        token_expiry_threshold_seconds=30,
    )
    return provider, raw_store


def create_mcp(service: Any, settings: Any) -> FastMCP:
    """创建完整 MCP 服务；本地无 OAuth 配置时便于离线测试。"""

    provider, _oauth_store = _provider(settings)

    server = FastMCP(
        "personal-crm",
        instructions="只读微信摘要，不代发消息；修改工具会返回 before/after。",
        auth=provider,
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
    """返回适配公网 Agent 客户端的无状态 Streamable HTTP ASGI 应用。"""

    public_hostname = urlsplit(settings.public_base_url).hostname
    # Cloudflare/Nginx 保留公网 Host；本地与容器名只用于健康检查和离线验收。
    allowed_hosts = ["localhost", "127.0.0.1", "personal-crm"]
    if public_hostname:
        allowed_hosts.insert(0, public_hostname)
    # 显式覆盖 ChatGPT、Claude、Grok 的网页来源，避免浏览器客户端被来源保护误拒绝。
    allowed_origins = [
        "https://chatgpt.com",
        "https://claude.ai",
        "https://claude.com",
        "https://grok.com",
        "https://x.ai",
        "https://x.com",
    ]
    return create_mcp(service, settings).http_app(
        path="/mcp",
        transport="streamable-http",
        # ChatGPT 的 OAuth 回调会立即初始化并枚举工具；无状态模式避免等待 GET 事件流超时。
        stateless_http=True,
        json_response=False,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
