"""Lossless document extraction. Excerpts are never presented as generated summaries."""
from __future__ import annotations

import re
import json

from .contracts import BLOCK_CHARS, ContentBlock, ProcessedContent

PROCESSOR = "document-v1"
PROFILE_VERSION = 2
KINDS = ("memo", "memory", "hermes_execution_report", "legacy_review_report")


def accepts(record):
    return record["kind"] in KINDS and (record["kind"] != "hermes_execution_report" or isinstance(record["normalized"].get("content", record["raw"].get("content")), str))


def process(rows):
    if not rows: return None
    if len(rows) != 1:
        raise ValueError("document_requires_one_record")
    row = rows[0]
    raw, normal = row["raw"], row["normalized"]
    body = normal.get("content", raw.get("document", {}).get("text") if row["kind"] == "legacy_review_report" else raw.get("content"))
    if not isinstance(body, str):
        raise ValueError("document_body_missing")
    # NUL remains in the archived input and evidence; PG text cannot store it.
    warnings = ["nul_replaced_in_reading_copy"] if "\x00" in body else []
    readable = body.replace("\x00", "\uFFFD")
    daily = re.match(r"\s*#日报\s+(\d{4}-\d{2}-\d{2})(?:\s|$)", readable)
    if daily:
        from datetime import date
        try: date.fromisoformat(daily[1])
        except ValueError: daily = None
    heading = re.search(r"(?m)^#{1,6}\s+(.+?)\s*$", readable)
    first = next((s.strip() for s in readable.splitlines() if s.strip()), "空笔记")
    variant = "daily_review" if daily else "execution_log" if row["kind"] == "hermes_execution_report" else "memory" if row["kind"] == "memory" else "legacy_review" if row["kind"] == "legacy_review_report" else "note"
    title = "日报 · " + daily[1] if daily else (heading[1] if heading else first)
    excerpt = readable[daily.end():].lstrip() if daily else readable
    blocks = []
    # Char offsets refer to the original input; replacement above is one-for-one.
    for start in range(0, len(readable), BLOCK_CHARS):
        end = min(len(readable), start + BLOCK_CHARS)
        blocks.append(ContentBlock(f"body:{start}", "markdown", readable[start:end],
                                  [dict(record_id=row["id"], input_hash=row["hash"],
                                        field="normalized.content" if isinstance(normal.get("content"), str) else "raw.document.text" if row["kind"] == "legacy_review_report" else "raw.content",
                                        char_start=start, char_end=end)], {"continuation": start > 0}))
    metadata = {"format": "markdown", "body_chars": len(body), "empty": not body,
                "origin": "source", "record_kind": row["kind"], "record_id": row["id"],
                "business_date": daily[1] if daily else None,
                "state": normal.get("state"), "pinned": bool(normal.get("pinned", False)),
                "source_ref": normal.get("source_ref", raw.get("path")),
                "assets": row["assets"], "relations": raw.get("relations", [])}
    payload = raw.get('payload', {})
    if isinstance(payload, str):
        try: payload = json.loads(payload)
        except ValueError:
            payload = {}; warnings.append('memo_payload_unreadable')
    if row['kind'] == 'memory':
        metadata.update(memory_metadata=normal.get('metadata'), categories=raw.get('categories', []), synthesized=raw.get('synthesized'), replaced_by=raw.get('replaced_by'), expiration_date=raw.get('expiration_date'))
    if row['kind'] == 'legacy_review_report':
        metadata.update(mode=raw['document'].get('mode'), report_scope='historical_output')
    metadata['tags'] = [tag for tag in payload.get('tags', []) if isinstance(tag, str)] if isinstance(payload, dict) and isinstance(payload.get('tags'), list) else []
    return ProcessedContent("document", variant, title[:160], excerpt[:500], blocks, metadata,
                            warnings=warnings)
