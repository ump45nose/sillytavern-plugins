"""客户端回调兼容冒烟，使用运行时实际采用的 FastMCP 校验器。"""

import pytest
from fastmcp.server.auth.redirect_validation import validate_redirect_uri

from mcp_platform.config import RuntimeConfig


@pytest.mark.parametrize("uri", [
    "https://chatgpt.com/connector_platform/oauth/callback",
    "https://grok.com/connectors-oauth-exchange-code/",
    "https://grok.com/connectors-oauth-exchange-code",
    "https://bot.grok.com/oauth/callback",
    "grokbot://mcp/oauth/callback",
    "https://www.cursor.com/agents/mcp/oauth/callback",
    "https://cursor.com/agents/mcp/oauth/callback",
    "cursor://anysphere.cursor-mcp/oauth/callback",
    "cursor://anysphere.cursor-mcp/oauth/return",
    "http://localhost:8787/callback",
    "http://127.0.0.1:51327/callback",
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
])
def test_supported_client_callbacks(uri):
    config = RuntimeConfig(name="smoke", development_no_auth=True)
    assert validate_redirect_uri(uri, config.client_redirect_uris)


@pytest.mark.parametrize("uri", [
    "https://evil.example/oauth/callback",
    "https://grok.com.evil.example/oauth/callback",
    "https://grok.com@evil.example/oauth/callback",
    "http://grok.com/connectors-oauth-exchange-code/",
    "https://grok.com:8443/connectors-oauth-exchange-code/",
    "https://www.cursor.com/other/callback",
    "cursor://evil.example/oauth/callback",
    "cursor://anysphere.cursor-mcp/other/callback",
    "grokbot://evil.example/oauth/callback",
    "grokbot://mcp/other/callback",
    "https://claude.ai/other/callback",
])
def test_untrusted_callbacks_rejected(uri):
    config = RuntimeConfig(name="smoke", development_no_auth=True)
    assert not validate_redirect_uri(uri, config.client_redirect_uris)


def test_explicit_env_policy_stays_restrictive(monkeypatch):
    monkeypatch.setenv("MCP_DEVELOPMENT_NO_AUTH", "true")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PUBLIC_BASE_URL", "")
    monkeypatch.setenv("ALLOWED_CLIENT_REDIRECT_URIS", " https://private.example/callback , ")
    config = RuntimeConfig.from_env("smoke")
    assert validate_redirect_uri("https://private.example/callback", config.client_redirect_uris)
    assert not validate_redirect_uri(
        "https://grok.com/connectors-oauth-exchange-code/", config.client_redirect_uris
    )
    monkeypatch.delenv("ALLOWED_CLIENT_REDIRECT_URIS")
    default = RuntimeConfig.from_env("smoke")
    assert validate_redirect_uri(
        "https://grok.com/connectors-oauth-exchange-code/", default.client_redirect_uris
    )
    config.client_redirect_uris.clear()
    assert default.client_redirect_uris
