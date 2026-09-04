"""从本机 WeLink 读取摘要并可靠推送到 NAS。"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .checkpoint import load, save
from .config import ConnectorConfig, as_datetime


@dataclass
class SyncResult:
    """一次同步的可观察结果。"""

    batch_id: str
    interactions: list[dict[str, Any]]
    facts: list[dict[str, Any]]
    sent: bool
    errors: list[str]


class WeChatConnector:
    """只出站运行的 Mac 微信连接器。"""

    def __init__(self, config: ConnectorConfig, client: Any | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout)

    def _get(self) -> list[dict[str, Any]]:
        """读取 WeLink，并兼容常见 list/data/items/messages 响应外壳。"""

        response = self.client.get(
            self.config.adapter_base_url.rstrip("/") + "/" + self.config.adapter_path.lstrip("/")
        )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, list):
            return body
        for key in ("data", "items", "messages", "interactions"):
            if isinstance(body, dict) and isinstance(body.get(key), list):
                return body[key]
        return []

    @staticmethod
    def _key(event: dict[str, Any]) -> str:
        """优先使用上游消息 ID；缺失时用不出站的本地内容组合生成键。"""

        raw = event.get("id") or event.get("message_id")
        if not raw:
            raw = "|".join(
                str(event.get(key, ""))
                for key in ("contact", "sender", "timestamp", "text", "content")
            )
        return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()

    def _filter(self, event: dict[str, Any]) -> bool:
        """在生成任何出站数据前应用白名单与时间窗口。"""

        contact = str(event.get("contact") or event.get("peer") or event.get("sender") or "")
        occurred_at = as_datetime(
            event.get("timestamp") or event.get("created_at") or event.get("time")
        )
        if self.config.allowed_contacts and contact not in self.config.allowed_contacts:
            return False
        if self.config.since and (not occurred_at or occurred_at < self.config.since):
            return False
        return not (self.config.until and occurred_at and occurred_at > self.config.until)

    @staticmethod
    def _safe_summary(event: dict[str, Any], person_name: str) -> str:
        """使用上游摘要或无正文的降级描述，禁止把原始消息伪装成摘要。"""

        source_text = str(event.get("text") or event.get("content") or "").strip()
        candidate = str(event.get("summary") or "").strip()
        if candidate and candidate != source_text and len(candidate) <= 1000:
            return candidate
        message_type = str(event.get("message_type") or event.get("type") or "消息")
        return f"与 {person_name} 发生一次微信{message_type}互动"

    @staticmethod
    def _facts(
        event: dict[str, Any], person_name: str, wxid: str | None, event_key: str
    ) -> list[dict[str, Any]]:
        """只接受上游明确给出的结构化 facts，不从一条消息臆造人物事实。"""

        occurred_at = as_datetime(
            event.get("timestamp") or event.get("created_at") or event.get("time")
        )
        result: list[dict[str, Any]] = []
        for item in event.get("facts") or []:
            if not isinstance(item, dict) or not str(item.get("content") or "").strip():
                continue
            result.append(
                {
                    "person_name": person_name,
                    "wxid": wxid,
                    "fact_type": item.get("fact_type", "other"),
                    "content": str(item["content"]).strip()[:2000],
                    "observed_at": occurred_at.isoformat() if occurred_at else None,
                    "confidence": item.get("confidence"),
                    "source_event_key": event_key,
                }
            )
        return result

    def sync_once(self, dry_run: bool = False) -> SyncResult:
        """同步一次；读取或写入失败时均不推进本地 checkpoint。"""

        state = load(self.config.checkpoint_path)
        try:
            events = self._get()
        except Exception as error:
            return SyncResult("", [], [], False, [f"welink: {type(error).__name__}"])

        interactions: list[dict[str, Any]] = []
        facts: list[dict[str, Any]] = []
        known_keys = set(state.get("keys", []))
        for event in events:
            event_key = self._key(event)
            if event_key in known_keys or not self._filter(event):
                continue
            person_name = str(
                event.get("contact") or event.get("peer") or event.get("sender") or ""
            ).strip()
            occurred_at = as_datetime(
                event.get("timestamp") or event.get("created_at") or event.get("time")
            )
            if not person_name or occurred_at is None:
                continue
            wxid = str(event.get("wxid") or "").strip() or None
            direction = str(event.get("direction") or "inbound")
            if direction not in {"inbound", "outbound", "mutual"}:
                direction = "inbound"
            interactions.append(
                {
                    "person_name": person_name,
                    "wxid": wxid,
                    "occurred_at": occurred_at.isoformat(),
                    "interaction_type": "message",
                    "channel": "wechat",
                    "direction": direction,
                    "summary": self._safe_summary(event, person_name),
                    "source_reference": f"welink:{event_key}",
                    "source_event_key": event_key,
                }
            )
            facts.extend(self._facts(event, person_name, wxid, event_key))

        batch_seed = [item["source_event_key"] for item in interactions]
        # 相同事件集合得到相同 UUID，NAS 重试和进程重启后仍可关联同一批次。
        batch_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                "personal-crm:welink:" + json.dumps(batch_seed, sort_keys=True),
            )
        )
        payload = {
            "batch_id": batch_id,
            "source": "welink",
            "interactions": interactions,
            "facts": facts,
        }
        if dry_run:
            return SyncResult(batch_id, interactions, facts, False, [])
        if not interactions and not facts:
            return SyncResult(batch_id, interactions, facts, False, [])
        if not self.config.webhook_url:
            return SyncResult(batch_id, interactions, facts, False, ["未配置 CRM_WEBHOOK_URL"])

        try:
            response = self.client.post(
                self.config.webhook_url,
                json=payload,
                headers={"X-Webhook-Token": self.config.webhook_token},
            )
            response.raise_for_status()
            body = response.json()
            errors = body.get("errors", []) if isinstance(body, dict) else ["invalid response"]
            if errors:
                return SyncResult(batch_id, interactions, facts, False, list(errors))
        except Exception as error:
            return SyncResult(
                batch_id, interactions, facts, False, [f"webhook: {type(error).__name__}"]
            )

        # 只有整个批次被 NAS 接受后才提交所有事件键。
        save(
            self.config.checkpoint_path,
            {
                "keys": list(known_keys | set(batch_seed)),
                "last_batch_id": batch_id,
            },
        )
        return SyncResult(batch_id, interactions, facts, True, [])
