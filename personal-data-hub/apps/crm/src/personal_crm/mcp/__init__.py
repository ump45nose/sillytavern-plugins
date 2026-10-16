"""Personal CRM 的 FastMCP 工具、资源与 Authelia OIDC 装配。"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server



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
               daily_reviews=None, daily_review_reports=None, hub_store=None, records_client=None) -> FastMCP:
    """创建完整 MCP 服务；本地无 OAuth 配置时便于离线测试。"""

    runtime = _runtime(settings)
    server = create_server(runtime, instructions='个人 CRM：维护人物资料与多人交互历史。正文可编辑，列表返回预览，详情和附件支持续读。')
    read_auth = _auth_check(settings, write=False)
    write_auth = _auth_check(settings, write=True)
    from personal_crm.archive.mcp import register_tools
    register_tools(server, service, read_auth, write_auth)

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
        register_tools(server, hub_store, read_auth, chat_reports=chat_reports, records_client=records_client)
    return server


def http_app(service: Any, settings: Any, *, events=None, chat_reports=None,
             daily_reviews=None, daily_review_reports=None, hub_store=None, records_client=None):
    """公共基座提供 HTTP、发现路由及经过同一认证的事件协议。"""

    server = create_mcp(service, settings, chat_reports=chat_reports,
                        daily_reviews=daily_reviews, daily_review_reports=daily_review_reports, hub_store=hub_store, records_client=records_client)
    config = _runtime(settings)
    if events is not None:
        return create_http_app(server, config, events=events)
    return create_http_app(server, config)
