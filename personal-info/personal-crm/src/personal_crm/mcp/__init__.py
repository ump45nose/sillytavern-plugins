"""Personal CRM 的 FastMCP 工具、资源与 Authelia OIDC 装配。"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server


def _runtime(settings: Any) -> RuntimeConfig:
    """适配原有 CRM 环境变量，保留 OAuth 状态格式与公开地址。"""

    return RuntimeConfig(
        name="personal-crm",
        host=settings.host,
        port=settings.port,
        development_no_auth=settings.mcp_development_no_auth,
        public_base_url=settings.public_base_url,
        oidc_discovery_url=settings.oidc_discovery_url,
        oidc_client_id=settings.oidc_client_id,
        oidc_client_secret=settings.oidc_client_secret,
        jwt_signing_key=settings.oauth_jwt_signing_key,
        storage_encryption_key=settings.oauth_storage_encryption_key,
        storage_path=settings.oauth_storage_path,
        storage_salt="personal-crm-oauth-v1",
        authorized_usernames=settings.authorized_usernames,
        read_only_usernames=settings.read_only_usernames,
        client_redirect_uris=settings.client_redirect_uris,
        allowed_hosts=["localhost", "127.0.0.1", "personal-crm"],
        allowed_origins=[
            "https://chatgpt.com",
            "https://claude.ai",
            "https://claude.com",
            "https://grok.com",
            "https://x.ai",
            "https://x.com",
        ],
        proxy_sni_compatibility=settings.mcp_proxy_sni_compatibility,
        requests_per_minute=0,
        tool_timeout_seconds=0,
        max_output_bytes=0,
    )


def _auth_check(settings: Any, *, write: bool):
    return authorize("write" if write else "read", _runtime(settings))


def create_mcp(archive, settings) -> FastMCP:
    """人物、交互与附件的 14 个工具。"""
    server = create_server(
        _runtime(settings),
        instructions=(
            "个人 CRM：维护人物基本资料及与一个或多个人的交互历史。"
            "提供人物、交互和附件的读写；交互正文可直接编辑。"
            "列表返回预览；详情与附件支持分页续读。"
        ),
    )
    from personal_crm.archive.mcp import register_tools

    register_tools(
        server, archive, _auth_check(settings, write=False), _auth_check(settings, write=True)
    )
    return server


def http_app(archive, settings):
    from .protocol import attach

    config = _runtime(settings)
    server = create_mcp(archive, settings)
    return attach(create_http_app(server, config), server, config)
