"""Connect directly to the email service through native MCP stdio or OAuth."""

from contextlib import asynccontextmanager
import os
import json
from pathlib import Path
import sys

import yaml
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


def email_payload(result):
    """Normalize MCP 1.x/2.x result fields and reject service errors."""
    if getattr(result, "is_error", getattr(result, "isError", False)):
        detail = " ".join(getattr(block, "text", "") for block in getattr(result, "content", ()))
        raise RuntimeError(detail[:240] or "email service returned an error")
    structured = getattr(result, "structured_content", getattr(result, "structuredContent", None))
    if isinstance(structured, dict):
        return structured
    for block in getattr(result, "content", ()):
        value = getattr(block, "text", None)
        if isinstance(value, str):
            try:
                payload = json.loads(value)
            except ValueError:
                continue
            if isinstance(payload, dict):
                return payload
    raise RuntimeError("email service returned no JSON object")


@asynccontextmanager
async def email_session():
    settings_path = Path(os.environ.get("HERMES_CRON_CONFIG", "/home/yuwk/cron/env/hermes.local.json"))
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    if settings.get("email_transport") == "service-stdio":
        # Native service interface; account credentials remain in its container.
        command = StdioServerParameters(command="docker", args=[
            "exec", "-i", settings["email_container"], "python", "-u", "-c",
            "from mcp_email_server.app import mcp; mcp.run(transport='stdio')",
        ])
        async with stdio_client(command) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                yield session
        return
    if settings.get("email_transport", "oauth") != "oauth":
        raise RuntimeError("unknown email cron transport")
    home = Path(os.environ.get("HERMES_HOME", "/home/hermes/.hermes/profiles/lingjun"))
    os.environ.setdefault("HERMES_HOME", str(home))
    agent = Path(os.environ.get("HERMES_AGENT_ROOT", "/home/hermes/.hermes/hermes-agent"))
    sys.path.insert(0, str(agent))
    from tools.mcp_oauth import suppress_interactive_oauth
    from tools.mcp_oauth_manager import get_manager
    from tools.mcp_tool import sdk_httpx
    httpx = sdk_httpx()

    config = yaml.safe_load((home / "config.yaml").read_text())
    server = config["mcp_servers"]["email"]
    if server.get("auth") != "oauth":
        raise RuntimeError("email MCP must use OAuth in the profile config")
    # Cron can refresh cached credentials, but must never wait for a browser.
    with suppress_interactive_oauth():
        auth = get_manager().get_or_build_provider("email", server["url"], server.get("oauth"))
        if auth is None:
            raise RuntimeError("Hermes email OAuth support is unavailable")
        async with httpx.AsyncClient(auth=auth, timeout=30, trust_env=False) as http:
            async with streamable_http_client(server["url"], http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    yield session
