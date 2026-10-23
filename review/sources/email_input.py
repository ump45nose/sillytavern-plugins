#!/usr/bin/env python3
"""收集四个账户的当日重要邮件元数据并写入日报证据文件。"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

from review.sources.email_transport import email_session, email_payload


APP_ROOT = Path(os.environ.get("REVIEW_APP_ROOT", str(Path(__file__).resolve().parents[2])))

from review.config import load_config  # noqa: E402
from review.sources.email_policy import EmailCandidatePolicy  # noqa: E402


def _full_day_since(zone: ZoneInfo) -> datetime:
    """返回业务时区自然日零点对应的 UTC 时间。"""

    local_midnight = datetime.combine(datetime.now(zone).date(), time.min, zone)
    return local_midnight.astimezone(timezone.utc)


def _occurred_at(message: dict[str, Any], fallback: datetime) -> str:
    """规范化邮件时间；缺失时使用采集时间而不伪造更精确时间。"""

    for key in ("date", "received_at", "timestamp", "sent_at"):
        value = message.get(key)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return (parsed if parsed.tzinfo else parsed.replace(tzinfo=fallback.tzinfo)).isoformat()
            except ValueError:
                continue
    return fallback.isoformat()


async def collect() -> dict[str, Any]:
    """只读邮件 MCP，输出可被 EvidencePipeline 消费的最小结构。"""

    config = load_config(APP_ROOT / ".env", APP_ROOT / "config/review.yaml")
    zone = config.timezone
    accounts = tuple(config.policy["sources"]["email_accounts"])
    since = _full_day_since(zone)
    collected_at = datetime.now(zone)
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    body_budget = int(config.policy["sources"]["email_body_budget"])
    candidate_policy = EmailCandidatePolicy(config.policy)
    async with email_session() as client:
        for account in accounts:
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
                messages = list(email_payload(response).get("emails") or [])
                # 附件和宽泛“通知”不再构成准入；必须先命中可用主题白名单。
                selected = [
                    message
                    for message in messages
                    if candidate_policy.assess(
                        str(message.get("subject") or ""),
                        str(message.get("sender") or ""),
                    )
                    is not None
                ]
                # 正文只用于确认重要性，不会写入 NAS 证据文件。
                to_read = selected[:body_budget]
                body_budget -= len(to_read)
                bodies: dict[str, str] = {}
                if to_read:
                    content = await client.call_tool(
                        "get_emails_content",
                        {
                            "account_name": account,
                            "email_ids": [str(message["email_id"]) for message in to_read],
                            "mailbox": "INBOX",
                            "mark_as_read": False,
                            "body_offset": 0,
                            "max_body_length": 3000,
                        },
                    )
                    bodies = {
                        str(item.get("email_id")): str(item.get("body") or "")
                        for item in email_payload(content).get("emails", [])
                    }
                for message in selected:
                    email_id = str(message.get("email_id", ""))
                    subject = str(message.get("subject") or "无主题").strip()
                    sender = str(message.get("sender") or account).strip()
                    body = bodies.get(email_id, "")
                    assessment = candidate_policy.assess(subject, sender, body)
                    if assessment is None:
                        continue
                    evidence.append(
                        {
                            "kind": assessment.kind.value,
                            "fact": assessment.fact,
                            "subject": assessment.subject,
                            "occurred_at": _occurred_at(message, collected_at),
                            "source_ref": f"{account}:{email_id}",
                        }
                    )
            except Exception as exc:
                errors.append(f"{account}: {type(exc).__name__}: {str(exc)[:120]}")

    # 账户和邮件 ID 组成天然幂等键；同一次窗口重复运行不会增加候选。
    if errors:
        raise RuntimeError("email collection incomplete: " + "; ".join(errors))
    unique = {item["source_ref"]: item for item in evidence}
    return {
        "date": collected_at.date().isoformat(),
        "generated_at": collected_at.isoformat(),
        "evidence": list(unique.values()),
        "errors": errors,
    }


def main() -> int:
    """原子写入当日邮件证据文件，并只输出数量级状态。"""

    config = load_config(APP_ROOT / ".env", APP_ROOT / "config/review.yaml")
    report = asyncio.run(collect())
    output_dir = config.path("REVIEW_EMAIL_BRIEF_DIR")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{report['date']}.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)
    print(json.dumps({"status": "partial" if report["errors"] else "ok", "date": report["date"], "evidence_count": len(report["evidence"]), "error_count": len(report["errors"])}, ensure_ascii=False))
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "type": type(exc).__name__, "message": str(exc)[:300]}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
