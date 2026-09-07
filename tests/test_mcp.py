"""MCP 工具注册和本地调用测试。"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from fastmcp.server.auth.redirect_validation import validate_redirect_uri

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.core import CrmService
from personal_crm.mcp import _auth_check, _provider, create_mcp
from personal_crm.storage import CrmRepository


@pytest.mark.asyncio
async def test_mcp_registers_required_tools_and_calls_person_flow():
    """验证十四个公共工具存在，且本地模式可完成建档和搜索。"""

    service = CrmService(CrmRepository("sqlite:///:memory:"))
    server = create_mcp(service, Settings())
    required = {
        "search_people",
        "get_person",
        "upsert_person",
        "list_interactions",
        "get_daily_summary",
        "record_interaction",
        "list_facts",
        "add_fact",
        "update_fact_status",
        "list_reminders",
        "create_reminder",
        "complete_reminder",
        "snooze_reminder",
        "skip_reminder",
        "get_weekly_metrics",
    }
    assert required <= {tool.name for tool in await server.list_tools()}
    result = await server.call_tool(
        "upsert_person",
        {"display_name": "MCP 联系人", "contact_interval_days": 30},
        run_middleware=False,
    )
    assert result.structured_content["after"]["display_name"] == "MCP 联系人"
    search = await server.call_tool("search_people", {"query": "MCP"}, run_middleware=False)
    assert search.structured_content["result"][0]["display_name"] == "MCP 联系人"


@pytest.mark.asyncio
async def test_daily_summary_excludes_private_text_and_groups_changes():
    """验证每日 MCP 汇总只有计数和人物名，不返回互动或事实正文。"""

    service = CrmService(CrmRepository("sqlite:///:memory:"))
    person = service.create_person("张三")
    interaction, _created, _completed = service.record_interaction(
        person_id=person.id,
        occurred_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        direction="mutual",
        summary="不应出现在每日汇总里的私密摘要",
    )
    service.record_fact(
        person_id=person.id,
        fact_type="preference",
        content="不应出现在每日汇总里的事实正文",
        observed_at=datetime(2026, 9, 6, 12, 5, tzinfo=UTC),
        source_interaction_id=interaction.id,
    )
    server = create_mcp(service, Settings())
    result = await server.call_tool(
        "get_daily_summary",
        {"day": "2026-09-06", "timezone": "Asia/Shanghai"},
        run_middleware=False,
    )
    summary = result.structured_content
    assert summary["interactions"]["count"] == 1
    assert summary["interactions"]["people"] == ["张三"]
    assert summary["facts"]["count"] == 1
    assert "私密摘要" not in str(summary)
    assert "事实正文" not in str(summary)


def oidc_settings(tmp_path, **overrides):
    """构造不包含真实秘密的 Authelia OIDC 测试配置。"""

    values = {
        "public_base_url": "https://crm.example.com",
        "oidc_discovery_url": "https://auth.example.com/.well-known/openid-configuration",
        "oidc_client_id": "personal-crm",
        "oidc_client_secret": "test-client-secret",
        "oidc_authorized_usernames": "yuwk",
        "oauth_jwt_signing_key": "j" * 32,
        "oauth_storage_encryption_key": "s" * 32,
        "oauth_storage_path": str(tmp_path / "oauth"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def mock_oidc_discovery(monkeypatch):
    """隔离网络并返回满足 OIDC 严格校验的 Authelia 元数据。"""

    metadata = OIDCConfiguration.model_validate(
        {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/api/oidc/authorization",
            "token_endpoint": "https://auth.example.com/api/oidc/token",
            "jwks_uri": "https://auth.example.com/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile", "offline_access"],
        }
    )
    monkeypatch.setattr(
        OIDCConfiguration,
        "get_oidc_configuration",
        classmethod(lambda cls, config_url, *, strict, timeout_seconds: metadata),
    )


def test_oauth_requires_authorized_oidc_usernames(tmp_path):
    """验证生产 OAuth 不允许遗漏 Authelia 用户白名单。"""

    service = CrmService(CrmRepository("sqlite:///:memory:"))
    settings = oidc_settings(
        tmp_path,
        oidc_authorized_usernames="",
    )
    with pytest.raises(ValueError, match="OIDC_AUTHORIZED_USERNAMES"):
        create_mcp(service, settings)


def test_oidc_authorization_uses_upstream_preferred_username(tmp_path):
    """验证 OIDCProxy 的嵌套上游用户名控制读写权限。"""

    settings = oidc_settings(
        tmp_path,
        oidc_authorized_usernames="yuwk,reader",
        oidc_read_only_usernames="reader",
    )
    read_check = _auth_check(settings, write=False)
    write_check = _auth_check(settings, write=True)
    owner = SimpleNamespace(
        token=SimpleNamespace(claims={"upstream_claims": {"preferred_username": "yuwk"}})
    )
    reader = SimpleNamespace(token=SimpleNamespace(claims={"preferred_username": "reader"}))
    stranger = SimpleNamespace(token=SimpleNamespace(claims={"preferred_username": "other"}))
    assert read_check(owner)
    assert write_check(owner)
    assert read_check(reader)
    assert not write_check(reader)
    assert not read_check(stranger)


@pytest.mark.asyncio
async def test_oidc_storage_accepts_cimd_url_client_id(tmp_path, mock_oidc_discovery):
    """验证 ChatGPT CIMD URL 经文件名清洗后可持久化，不会被斜杠拆成目录。"""

    _provider_instance, raw_store = _provider(oidc_settings(tmp_path))
    assert raw_store is not None
    await raw_store.put(
        key="https://chatgpt.com/oauth/client.json",
        value={"registered": True},
        collection="mcp-oauth-proxy-clients",
    )
    stored = await raw_store.get(
        key="https://chatgpt.com/oauth/client.json",
        collection="mcp-oauth-proxy-clients",
    )
    assert stored == {"registered": True}


def test_default_oauth_redirect_allowlist_supports_agents_and_ai_vendors():
    """验证默认白名单覆盖本机 Agent 与 GPT、Claude、Grok 厂商域名。"""

    redirect_uris = Settings().client_redirect_uris
    assert "http://localhost:*" in redirect_uris
    assert "http://127.0.0.1:*" in redirect_uris
    for vendor_pattern in {
        "https://chatgpt.com/*",
        "https://*.chatgpt.com/*",
        "https://openai.com/*",
        "https://*.openai.com/*",
        "https://claude.ai/*",
        "https://*.claude.ai/*",
        "https://anthropic.com/*",
        "https://*.anthropic.com/*",
        "https://grok.com/*",
        "https://*.grok.com/*",
        "https://x.ai/*",
        "https://*.x.ai/*",
        "https://x.com/*",
        "https://*.x.com/*",
    }:
        assert vendor_pattern in redirect_uris
    # 使用真实形态的路径验证主域名和子域名，而不只检查配置字符串是否存在。
    for callback_uri in {
        "https://chatgpt.com/backend-api/aip/connectors/mcp/oauth_config",
        "https://oauth.openai.com/connector/callback",
        "https://claude.ai/api/mcp/auth_callback",
        "https://console.anthropic.com/oauth/callback",
        "https://grok.com/oauth/callback",
        "https://console.x.ai/oauth/callback",
        "https://x.com/i/oauth/callback",
    }:
        assert validate_redirect_uri(callback_uri, redirect_uris)
    assert not validate_redirect_uri("https://evil.example/oauth/callback", redirect_uris)


def test_streamable_http_mcp_initialize():
    """验证无状态 /mcp 可完成初始化和工具枚举，不依赖长期 GET 会话。"""

    repository = CrmRepository("sqlite:///:memory:")
    # 上下文管理器会启动父 ASGI 与 FastMCP 共享的 lifespan。
    with TestClient(create_app(Settings(), repository)) as client:
        response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "1"},
                },
            },
        )
        tools_response = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "mcp-session-id" not in response.headers
    assert "personal-crm" in response.text
    assert tools_response.status_code == 200
    assert "search_people" in tools_response.text


def test_oauth_discovery_compatibility_endpoint(
    tmp_path, mock_oidc_discovery
):
    """验证无后缀发现端点直接返回 ChatGPT 可消费的资源元数据。"""

    settings = oidc_settings(tmp_path)
    repository = CrmRepository("sqlite:///:memory:")
    with TestClient(create_app(settings, repository)) as client:
        response = client.get("/.well-known/oauth-protected-resource", follow_redirects=False)
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json() == metadata.json()
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == "https://crm.example.com/mcp"
    assert metadata.json()["scopes_supported"] == ["openid", "profile", "offline_access"]
