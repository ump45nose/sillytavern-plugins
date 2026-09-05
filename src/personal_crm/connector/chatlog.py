"""chatlog-keeper 本地消息流适配器。"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import ConnectorConfig, as_datetime


class ChatlogSourceError(RuntimeError):
    """表示不包含聊天正文和本地标识的安全读取错误。"""


@dataclass(frozen=True)
class SourceBatch:
    """一次有界读取结果及其成功水位。"""

    events: list[dict[str, Any]]
    until: datetime


class ChatlogMessageSource:
    """通过 stdin/stdout 调用本机 message-stream-v1，不开放入站端口。"""

    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config

    def _verified_executable(self) -> Path:
        """验证可执行文件路径及可选 SHA-256，避免静默运行被替换的二进制。"""

        executable = Path(self.config.chatlog_executable).expanduser()
        if not executable.is_file():
            raise ChatlogSourceError("executable_unavailable")
        if self.config.chatlog_expected_sha256:
            digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            if digest != self.config.chatlog_expected_sha256.lower():
                raise ChatlogSourceError("executable_checksum_mismatch")
        return executable

    def _scopes(self) -> list[dict[str, str]]:
        """读取五人白名单映射，并按协议规定的 scope 顺序排序。"""

        try:
            raw = json.loads(
                Path(self.config.chatlog_scopes_path)
                .expanduser()
                .read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise ChatlogSourceError("scopes_unavailable") from error
        if not isinstance(raw, list):
            raise ChatlogSourceError("scopes_invalid")

        scopes: list[dict[str, str]] = []
        allowed = self.config.allowed_contacts
        for item in raw:
            if not isinstance(item, dict):
                raise ChatlogSourceError("scopes_invalid")
            requested_id = str(item.get("requested_id") or "").strip()
            account_id = str(item.get("account_id") or "").strip()
            conversation_id = str(item.get("conversation_id") or "").strip()
            conversation_type = str(item.get("conversation_type") or "").strip()
            if (
                not requested_id
                or not account_id
                or not conversation_id
                or conversation_type not in {"direct", "group"}
            ):
                raise ChatlogSourceError("scopes_invalid")
            # 双重执行白名单：环境配置和映射文件必须同时允许该联系人。
            if allowed and requested_id not in allowed:
                continue
            scopes.append(
                {
                    "requested_id": requested_id,
                    "person_name": str(item.get("person_name") or requested_id).strip(),
                    "account_id": account_id,
                    "conversation_id": conversation_id,
                    "conversation_type": conversation_type,
                }
            )
        if allowed and {item["requested_id"] for item in scopes} != allowed:
            raise ChatlogSourceError("scopes_allowlist_mismatch")
        return sorted(
            scopes,
            key=lambda item: (
                item["account_id"],
                item["conversation_id"],
                item["conversation_type"],
            ),
        )

    def _window(self, state: dict[str, Any]) -> tuple[datetime, datetime]:
        """生成可重试的一天窗口；成功后再由 Connector 提交水位。"""

        now = datetime.now(UTC)
        configured_since = self.config.since or (now - timedelta(days=1))
        previous = as_datetime(state.get("last_synced_at"))
        start = configured_since
        if previous:
            start = max(
                configured_since,
                previous - timedelta(seconds=self.config.chatlog_overlap_seconds),
            )
        end = min(start + timedelta(seconds=self.config.chatlog_window_seconds), now)
        if self.config.until:
            end = min(end, self.config.until)
        return start, max(start, end)

    @staticmethod
    def _event(record: dict[str, Any], scope: dict[str, str]) -> dict[str, Any] | None:
        """把真实消息立即裁剪为无正文事件，原始 content 不离开当前调用栈。"""

        occurred_at = as_datetime(record.get("ts"))
        if occurred_at is None:
            return None
        identity = {
            "account_id": scope["account_id"],
            "conversation_id": scope["conversation_id"],
            "server_id": record.get("server_id"),
            "source_offset": record.get("source_offset"),
            "ts": record.get("ts"),
        }
        event_id = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return {
            "id": event_id,
            "contact": scope["person_name"],
            "wxid": scope["requested_id"],
            "timestamp": occurred_at.isoformat(),
            "direction": "outbound" if record.get("is_self") is True else "inbound",
            "message_type": str(record.get("msg_type") or "消息"),
        }

    def read(self, state: dict[str, Any]) -> SourceBatch:
        """读取一个完整 NDJSON 批次；协议未 complete 时整批失败。"""

        executable = self._verified_executable()
        scopes = self._scopes()
        start, end = self._window(state)
        request = {
            "protocol": "message-stream-v1",
            "version": 1,
            "source": "wechat",
            "since_ts": start.timestamp(),
            "until_ts": end.timestamp(),
            "page_size": self.config.chatlog_page_size,
            "scopes": [
                {
                    "account_id": item["account_id"],
                    "conversation_id": item["conversation_id"],
                    "conversation_type": item["conversation_type"],
                }
                for item in scopes
            ],
        }
        try:
            completed = subprocess.run(
                [str(executable), "message-stream-v1", "--selection-stdin"],
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ChatlogSourceError(type(error).__name__) from error

        events: list[dict[str, Any]] = []
        complete = False
        try:
            for line in completed.stdout.splitlines():
                frame = json.loads(line)
                frame_type = frame.get("frame")
                if frame_type == "error":
                    raise ChatlogSourceError(str(frame.get("code") or "read_failed"))
                if frame_type == "record":
                    scope_index = frame.get("scope_index")
                    if not isinstance(scope_index, int) or not 0 <= scope_index < len(scopes):
                        raise ChatlogSourceError("scope_mismatch")
                    event = self._event(frame.get("record") or {}, scopes[scope_index])
                    if event:
                        events.append(event)
                elif frame_type == "complete":
                    complete = True
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ChatlogSourceError("invalid_stream") from error
        if completed.returncode != 0 or not complete:
            raise ChatlogSourceError("incomplete_stream")
        return SourceBatch(events=events, until=end)
