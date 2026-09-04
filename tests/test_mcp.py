"""MCP 工具注册和本地调用测试。"""

import pytest
from fastapi.testclient import TestClient

from personal_crm.app.server import create_app
from personal_crm.app.settings import Settings
from personal_crm.core import CrmService
from personal_crm.mcp import create_mcp
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


def test_oauth_requires_allowed_github_user_ids():
    """验证生产 OAuth 不允许遗漏 GitHub 用户白名单。"""

    service = CrmService(CrmRepository("sqlite:///:memory:"))
    settings = Settings(
        public_base_url="https://crm.example.com",
        github_client_id="client",
        github_client_secret="secret",
    )
    with pytest.raises(ValueError, match="GITHUB_ALLOWED_USER_IDS"):
        create_mcp(service, settings)


def test_streamable_http_mcp_initialize():
    """验证真实 /mcp 传输可完成 JSON-RPC initialize 握手。"""

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
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "personal-crm" in response.text


def test_oauth_discovery_compatibility_endpoint():
    """验证固定发现端点会跳转到 FastMCP 的权威资源元数据。"""

    settings = Settings(
        public_base_url="https://crm.example.com",
        github_client_id="client",
        github_client_secret="secret",
        github_allowed_user_ids="12345678",
        oauth_jwt_signing_key="a-long-local-only-test-signing-key",
    )
    repository = CrmRepository("sqlite:///:memory:")
    with TestClient(create_app(settings, repository)) as client:
        response = client.get("/.well-known/oauth-protected-resource", follow_redirects=False)
        metadata = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 307
    assert response.headers["location"] == "/.well-known/oauth-protected-resource/mcp"
    assert metadata.status_code == 200
    assert metadata.json()["resource"] == "https://crm.example.com/mcp"
