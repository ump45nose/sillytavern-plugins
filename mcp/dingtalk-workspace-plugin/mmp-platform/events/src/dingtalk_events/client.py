from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

ALLOWED_TOOLS = {
    "todo": "get_user_todos_in_current_org",
    "approval": "get_todo_tasks",
    "calendar": "list_calendar_events",
}


class SourceError(Exception):
    """Stable, nonsecret diagnostics; never include an upstream URL or body."""


def _nested_source_error(error: BaseException) -> SourceError | None:
    if isinstance(error, SourceError):
        return error
    for child in getattr(error, "exceptions", ()):
        found = _nested_source_error(child)
        if found is not None:
            return found
    return None


class _CredentialFilter(logging.Filter):
    def __init__(self, urls: list[str]):
        super().__init__()
        self.urls = tuple(urls)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        changed = False
        for url in self.urls:
            if url in message:
                message = message.replace(url, "[DingTalk upstream]")
                changed = True
        if changed:
            record.msg, record.args = message, ()
        # Transport tracebacks may repeat a credential-bearing URL.
        if record.exc_info:
            record.msg = str(record.msg) + " [transport exception redacted]"
            record.exc_info = None
            record.exc_text = None
        return True


def unwrap_result(value: Any) -> dict:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if not isinstance(value, dict):
        raise SourceError("invalid_response_shape")
    if value.get("isError") is True:
        raise SourceError("upstream_tool_error")
    if "structuredContent" in value or "content" in value:
        payload = value.get("structuredContent")
        if not isinstance(payload, dict):
            payloads = []
            for block in value.get("content", []):
                if block.get("type") == "text":
                    try:
                        parsed = json.loads(block["text"])
                    except (ValueError, KeyError):
                        continue
                    if isinstance(parsed, dict):
                        payloads.append(parsed)
            if len(payloads) != 1:
                raise SourceError("invalid_response_shape")
            payload = payloads[0]
        value = payload
    if value.get("success") in (False, "false", "False", 0):
        raise SourceError("upstream_business_error")
    for key in ("error_code", "errorCode", "errcode"):
        if key in value and value[key] not in (0, "0", None, ""):
            raise SourceError("upstream_business_error")
    result = value.get("result")
    if not isinstance(result, dict):
        raise SourceError("missing_result_object")
    return result


class ReadOnlyMCPClient:
    """Uses the current account's three configured official services only."""

    def __init__(self, sources: dict[str, dict], timeout_seconds: int = 90):
        self.sources = sources
        self.timeout_seconds = timeout_seconds
        credential_filter = _CredentialFilter([v["url"] for v in sources.values() if v.get("url")])
        for name in ("httpx", "httpcore", "mcp.client.streamable_http"):
            logging.getLogger(name).addFilter(credential_filter)

    @asynccontextmanager
    async def session(self, source: str):
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        if source not in ALLOWED_TOOLS or source not in self.sources:
            raise SourceError("source_not_configured")

        async def check_response(response):
            if response.status_code in (401, 403):
                raise SourceError("upstream_authorization_required")
            if 300 <= response.status_code < 400:
                raise SourceError("upstream_redirect_refused")

        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(35.0, read=60.0), follow_redirects=False,
                    headers=self.sources[source].get("headers", {}),
                    event_hooks={"response": [check_response]},
                ) as http:
                    async with streamable_http_client(
                        self.sources[source]["url"], http_client=http
                    ) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()

                            async def call(arguments: dict) -> dict:
                                response = await session.call_tool(
                                    ALLOWED_TOOLS[source], arguments
                                )
                                return unwrap_result(response)

                            yield call
        except asyncio.CancelledError:
            raise
        except SourceError:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise SourceError("upstream_timeout") from None
        except Exception as error:
            source_error = _nested_source_error(error)
            if source_error is not None:
                raise source_error from None
            raise SourceError("upstream_unavailable") from None
