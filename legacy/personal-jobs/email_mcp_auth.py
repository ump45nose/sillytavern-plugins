"""Use the profile's Hermes OAuth cache for read-only email cron clients."""

from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys

import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def email_session():
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
