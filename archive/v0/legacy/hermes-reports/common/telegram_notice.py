"""Verified delivery through the dedicated Hermes notice bot."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


NOTICE_ENV = Path("/home/hermes/.hermes/.env")
EXPECTED_BOT = "yuwk_notice_bot"
MAX_MESSAGE_CHARS = 3900


def _token() -> str:
    value = os.environ.get("HERMES_NOTICE_BOT_TOKEN", "").strip()
    if value:
        return value.strip('"').strip("'")
    try:
        for line in NOTICE_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, raw = line.split("=", 1)
            if name.strip() == "HERMES_NOTICE_BOT_TOKEN":
                token = raw.strip().strip('"').strip("'")
                if token:
                    return token
    except OSError as exc:
        raise RuntimeError("cannot read Hermes notice-bot configuration") from exc
    raise RuntimeError("HERMES_NOTICE_BOT_TOKEN is not configured")


def _api(method: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8"))
        except Exception:
            raise RuntimeError(f"Telegram {method} failed with HTTP {exc.code}") from None
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(f"Telegram {method} request failed ({type(exc).__name__})") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        description = (
            result.get("description", "API returned ok=false")
            if isinstance(result, dict)
            else "invalid API response"
        )
        raise RuntimeError(f"Telegram {method} failed: {description}")
    return result


def _chunks(text: str) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > MAX_MESSAGE_CHARS:
        cut = remaining.rfind("\n", 0, MAX_MESSAGE_CHARS)
        if cut < MAX_MESSAGE_CHARS // 2:
            cut = MAX_MESSAGE_CHARS
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def send_report(chat_id: str, thread_id: str, text: str) -> int:
    parts = _chunks(text)
    if not parts:
        return 0
    token = _token()
    identity = _api("getMe", token).get("result")
    if not isinstance(identity, dict):
        raise RuntimeError("Telegram getMe returned an invalid bot identity")
    username = str(identity.get("username", "")).lstrip("@").casefold()
    if username != EXPECTED_BOT:
        raise RuntimeError("configured token does not identify @yuwk_notice_bot")

    for index, part in enumerate(parts, start=1):
        body = part if len(parts) == 1 else f"({index}/{len(parts)})\n{part}"
        result = _api("sendMessage", token, {
            "chat_id": str(chat_id),
            "message_thread_id": str(thread_id),
            "text": body,
            "disable_notification": "true",
        })
        message = result.get("result")
        if not isinstance(message, dict):
            raise RuntimeError("Telegram sendMessage returned an invalid message")
        chat = message.get("chat")
        returned_chat = str(chat.get("id", "")) if isinstance(chat, dict) else ""
        returned_thread = str(message.get("message_thread_id", ""))
        if returned_chat != str(chat_id) or returned_thread != str(thread_id):
            raise RuntimeError("Telegram accepted a report outside the configured chat/topic")
        if message.get("is_topic_message") is not True:
            raise RuntimeError("Telegram did not confirm topic delivery")
    return len(parts)
