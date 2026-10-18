"""私聊消息增量同步；服务端负责人物和交互聚合。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from .chatlog import ChatlogMessageSource
from .checkpoint import load, save


@dataclass
class SyncResult:
    messages: list[dict]
    sent: bool
    errors: list[str]
    accepted: int = 0
    duplicates: int = 0


class WeChatConnector:
    def __init__(self, config, client=None, source=None):
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout)
        self.source = source or ChatlogMessageSource(config)

    def sync_once(self, dry_run=False):
        try:
            state = load(self.config.checkpoint_path)
            if state.get("last_synced_at"):
                from .config import as_datetime

                at = as_datetime(state["last_synced_at"])
                if at is None or at.tzinfo is None:
                    raise ValueError("checkpoint_invalid")
        except (OSError, ValueError):
            return SyncResult([], False, ["checkpoint_unreadable"])
        # Establish the activation boundary once; first failure must not move it forward.
        if not state.get("last_synced_at"):
            state["last_synced_at"] = (self.config.since or datetime.now(UTC)).isoformat()
            state["enabled_since"] = state["last_synced_at"]
            if not dry_run:
                save(self.config.checkpoint_path, state)
        media_queue = None
        if self.config.media_enabled and not dry_run:
            from .media import MediaQueue

            media_queue = MediaQueue(self.config)
            try:
                media_queue.initialize()
            except (OSError, ValueError):
                return SyncResult([], False, ["media_queue_unavailable"])
        try:
            batch = self.source.read(state)
        except Exception as exc:
            return SyncResult([], False, [f"chatlog: {type(exc).__name__}"])
        outgoing, local_media = [], []
        for event in batch.events:
            message = event["message"]
            if message["conversation_type"] != "direct":
                continue
            record = message["record"]
            event_key = hashlib.sha256(event["id"].encode()).hexdigest()
            key = event.get("source_message_key") or event_key
            typ = int(record.get("msg_type") or 0)
            media = None
            if typ in {3, 34, 43, 49}:
                labels = {3: "图片", 34: "语音", 43: "视频", 49: "文件"}
                meta = record.get("attachment_meta") or {}
                if typ != 49 or meta.get("kind") == "file":
                    media = {
                        "name": meta.get("filename") or labels[typ],
                        "media_type": "application/octet-stream",
                    }
            outgoing.append(
                dict(
                    key=key,
                    account=message["account_namespace"],
                    peer=message["conversation_id"],
                    name=event["contact"],
                    sent_at=event["timestamp"],
                    sender=event["contact"],
                    is_self=record.get("is_self") is True,
                    content=record["content"],
                    attachment=media,
                )
            )
            if media_queue and media:
                local_media.append(
                    dict(
                        source_event_key=event_key,
                        source_message_key=event.get("source_message_key"),
                        occurred_at=event["timestamp"],
                        message=dict(
                            conversation_id=message["conversation_id"],
                            _media_account_id=event.get("_media_account_id"),
                            record={k: record[k] for k in ("ts", "server_id", "msg_type")},
                        ),
                    )
                )
        if dry_run:
            return SyncResult(outgoing, False, [])
        if not self.config.webhook_url:
            return SyncResult(outgoing, False, ["CRM_WEBHOOK_URL is not configured"])
        accepted = duplicates = 0
        try:
            pending = media_queue.pending_keys()[:500] if media_queue else []
            missing = set()
            parts = max(1, (len(outgoing) + 499) // 500)
            for part in range(parts):
                response = self.client.post(
                    self.config.webhook_url,
                    json={
                        "messages": outgoing[part * 500 : (part + 1) * 500],
                        "client_id": self.config.client_id,
                        "pending_media_keys": pending if part == parts - 1 else [],
                        "synced_through": batch.until.isoformat() if part == parts - 1 else None,
                    },
                    headers={"X-Webhook-Token": self.config.webhook_token},
                )
                response.raise_for_status()
                result = response.json()
                if result.get("errors"):
                    return SyncResult(outgoing, False, ["ingest_rejected"])
                accepted += result["accepted"]
                duplicates += result["duplicates"]
                missing.update(result["missing_media_keys"])
            if media_queue:
                checked = pending + [m["key"] for m in outgoing]
                media_queue.reconcile(checked, missing, local_media)
        except httpx.HTTPStatusError as exc:
            return SyncResult(outgoing, False, [f"ingest: HTTP {exc.response.status_code}"])
        except Exception as exc:
            return SyncResult(outgoing, False, [f"ingest: {type(exc).__name__}"])
        save(
            self.config.checkpoint_path,
            {
                **({"enabled_since": state["enabled_since"]} if state.get("enabled_since") else {}),
                "last_synced_at": batch.until.isoformat(),
            },
        )
        return SyncResult(outgoing, True, [], accepted, duplicates)
