#!/usr/bin/env python3
"""Collect bounded, read-only email input for the Lingjun work brief."""

from __future__ import annotations

import asyncio
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hermes"))
from email_mcp_auth import email_session


PROFILE_HOME = Path("/home/hermes/.hermes/profiles/lingjun")
OUTPUT_DIR = PROFILE_HOME / "cron/output/dd8e905a387a"
ACCOUNTS = ("gmail1", "gmail2", "qq", "wecom")
IMPORTANT_WORDS = (
    "urgent", "action required", "deadline", "interview", "offer", "invoice",
    "payment", "security", "verification", "meeting", "alert", "approval",
    "紧急", "待办", "截止", "面试", "录用", "账单", "发票", "安全",
    "验证", "会议", "告警", "审批", "工资", "合同",
)
MAX_BODY_EMAILS = 12


def _tool_payload(result: object) -> dict:
    """Return a JSON object from MCP 2.x structured or text tool output."""
    if bool(getattr(result, "is_error", getattr(result, "isError", False))):
        raise RuntimeError("MCP tool returned an error")
    structured = getattr(result, "structured_content", getattr(result, "structuredContent", None))
    if isinstance(structured, dict):
        return structured
    for item in getattr(result, "content", ()):
        text = getattr(item, "text", None)
        if not isinstance(text, str):
            continue
        try:
            payload = json.loads(text)
        except ValueError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("MCP tool returned no JSON object")


def _incremental_since() -> datetime:
    """Advance only from a run whose data-collection script actually succeeded."""
    floor = datetime.now(timezone.utc) - timedelta(days=7)
    if not OUTPUT_DIR.is_dir():
        return floor
    outputs = sorted(OUTPUT_DIR.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    for output in outputs:
        try:
            text = output.read_text(encoding="utf-8")
        except OSError:
            continue
        if "\n## Script Output\n" not in text:
            continue
        try:
            local_run = datetime.strptime(output.stem, "%Y-%m-%d_%H-%M-%S").astimezone()
        except ValueError:
            continue
        # Small overlap avoids losing a message that arrived while the prior
        # metadata request was in flight. Duplicate noise is preferable to loss.
        return max(floor, (local_run - timedelta(minutes=5)).astimezone(timezone.utc))
    return floor


def _needs_body(message: dict) -> bool:
    subject = str(message.get("subject") or "").strip().lower()
    sender = str(message.get("sender") or "").strip().lower()
    return (
        not subject
        or bool(message.get("attachments"))
        or any(word in f"{subject} {sender}" for word in IMPORTANT_WORDS)
    )


async def collect(since_override: datetime | None = None) -> dict:
    since = since_override or _incremental_since()
    report = {
        "since": since.isoformat(),
        "accounts": {},
        "errors": {},
        "body_reads": 0,
        "body_deferred": 0,
    }
    body_budget = MAX_BODY_EMAILS
    async with email_session() as client:
        for account in ACCOUNTS:
            try:
                response = await client.call_tool(
                    "list_emails_metadata",
                    {
                        "account_name": account,
                        "page": 1,
                        "page_size": 30,
                        "since": since.isoformat(),
                        "order": "desc",
                        "mailbox": "INBOX",
                    },
                )
                payload = _tool_payload(response)
                emails = list(payload.get("emails") or [])
                account_result = {
                    "total": int(payload.get("total") or len(emails)),
                    "emails": emails,
                }
                selected = [mail for mail in emails if _needs_body(mail)]
                to_read = selected[:body_budget]
                body_budget -= len(to_read)
                report["body_deferred"] += max(0, len(selected) - len(to_read))
                if to_read:
                    content = await client.call_tool(
                        "get_emails_content",
                        {
                            "account_name": account,
                            "email_ids": [str(mail["email_id"]) for mail in to_read],
                            "mailbox": "INBOX",
                            "mark_as_read": False,
                            "body_offset": 0,
                            "max_body_length": 6000,
                        },
                    )
                    bodies = {
                        str(item.get("email_id")): item
                        for item in _tool_payload(content).get("emails", [])
                    }
                    for mail in account_result["emails"]:
                        body = bodies.get(str(mail.get("email_id")))
                        if body:
                            mail["body"] = body.get("body") or ""
                    report["body_reads"] += len(bodies)
                report["accounts"][account] = account_result
            except Exception as exc:
                report["errors"][account] = f"{type(exc).__name__}: {exc}"
                report["accounts"][account] = {"total": 0, "emails": []}
    report["new_total"] = sum(
        int(value.get("total") or 0) for value in report["accounts"].values()
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", help="Explicit ISO-8601 lower bound for recovery runs")
    args = parser.parse_args()
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        since = since.astimezone(timezone.utc)
    report = asyncio.run(collect(since))
    if report["errors"]:
        raise RuntimeError("email collection incomplete; failed accounts: " + ", ".join(report["errors"]))
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
