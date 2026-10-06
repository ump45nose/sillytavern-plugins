#!/usr/bin/env python3
"""Send text to a Telegram DM topic with hard delivery verification.

Success only when Telegram returns ok=true AND the message lands in the
requested message_thread_id (is_topic_message=true when thread_id set).

Usage:
  python3 telegram_dm_topic_send.py \
    --chat CHAT_ID --thread THREAD_ID \
    --text-file /path/to/body.txt

  printf '%s' "$BODY" | python3 telegram_dm_topic_send.py \
    --chat CHAT_ID --thread THREAD_ID --stdin

Env:
  TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN from profile .env (preferred)
  HTTPS_PROXY / HTTP_PROXY honored if already set; defaults to local 7890.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


PROFILE_ROOT = Path("/home/hermes/.hermes/profiles/lingjun")
ENV_PATH = PROFILE_ROOT / ".env"
DEFAULT_PROXY = "http://127.0.0.1:7890"


def _load_token() -> str:
    for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"):
        val = os.environ.get(key, "").strip().strip('"').strip("'")
        if val:
            return val
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN"):
                v = v.strip().strip('"').strip("'")
                if v:
                    return v
    raise SystemExit("missing TELEGRAM_BOT_TOKEN / TELEGRAM_TOKEN")


def _ensure_proxy() -> None:
    if not os.environ.get("HTTPS_PROXY") and not os.environ.get("https_proxy"):
        os.environ["HTTPS_PROXY"] = DEFAULT_PROXY
    if not os.environ.get("HTTP_PROXY") and not os.environ.get("http_proxy"):
        os.environ["HTTP_PROXY"] = DEFAULT_PROXY


def _read_text(args: argparse.Namespace) -> str:
    if args.stdin:
        text = sys.stdin.read()
    elif args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    else:
        raise SystemExit("provide --text-file, --text, or --stdin")
    text = text.strip()
    if not text:
        raise SystemExit("empty message body")
    # Telegram hard limit ~4096; keep a margin for safety
    if len(text) > 4000:
        raise SystemExit(f"message too long for single send: {len(text)} chars (max 4000)")
    return text


def send_topic_message(chat_id: str, thread_id: str | None, text: str) -> dict:
    token = _load_token()
    _ensure_proxy()
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_notification": "true",
    }
    if thread_id:
        payload["message_thread_id"] = str(thread_id)
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return json.loads(body)
        except Exception:
            raise SystemExit(f"telegram HTTP {e.code}: {body[:300]}") from e
    except Exception as e:
        raise SystemExit(f"telegram request failed: {e}") from e


def create_topic(chat_id: str, name: str) -> dict:
    token = _load_token()
    _ensure_proxy()
    data = urllib.parse.urlencode({"chat_id": chat_id, "name": name}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/createForumTopic",
        data=data,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            obj = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            obj = json.loads(body)
        except Exception:
            raise SystemExit(f"telegram HTTP {exc.code}") from exc
    if not obj.get("ok"):
        raise SystemExit(
            f"telegram ok=false error_code={obj.get('error_code')} "
            f"description={obj.get('description')}"
        )
    result = obj.get("result") or {}
    thread_id = result.get("message_thread_id")
    if thread_id is None:
        raise SystemExit("createForumTopic returned no message_thread_id")
    return {"ok": True, "chat_id": str(chat_id), "name": name, "message_thread_id": thread_id}


def verify(obj: dict, chat_id: str, thread_id: str | None) -> dict:
    if not obj.get("ok"):
        raise SystemExit(
            f"telegram ok=false error_code={obj.get('error_code')} "
            f"description={obj.get('description')}"
        )
    result = obj.get("result") or {}
    got_chat = str(((result.get("chat") or {}).get("id") or ""))
    got_thread = result.get("message_thread_id")
    is_topic = result.get("is_topic_message")
    message_id = result.get("message_id")

    if got_chat != str(chat_id):
        raise SystemExit(f"chat mismatch: expected {chat_id}, got {got_chat}")

    if thread_id:
        if got_thread is None or str(got_thread) != str(thread_id):
            raise SystemExit(
                f"thread mismatch: expected {thread_id}, got {got_thread}; "
                f"is_topic_message={is_topic}; message_id={message_id}"
            )
        if is_topic is False:
            raise SystemExit(
                f"is_topic_message=false for thread {thread_id}; message_id={message_id}"
            )

    return {
        "ok": True,
        "message_id": message_id,
        "chat_id": got_chat,
        "message_thread_id": got_thread,
        "is_topic_message": is_topic,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chat", required=True, help="Telegram chat id")
    parser.add_argument("--thread", default=None, help="DM topic / message_thread_id")
    parser.add_argument("--text-file", help="Path to message body")
    parser.add_argument("--text", help="Inline message body")
    parser.add_argument("--stdin", action="store_true", help="Read body from stdin")
    parser.add_argument("--create-topic", help="Create a DM forum topic and print its real thread id")
    args = parser.parse_args()

    if args.create_topic:
        print(json.dumps(create_topic(args.chat, args.create_topic), ensure_ascii=False))
        return 0

    text = _read_text(args)
    raw = send_topic_message(args.chat, args.thread, text)
    summary = verify(raw, args.chat, args.thread)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
