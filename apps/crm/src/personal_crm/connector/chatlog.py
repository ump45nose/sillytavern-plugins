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
        """目录仅用于定位私聊；不将目录对象导入人物表。"""
        try:
            pinned = json.loads(Path(self.config.chatlog_scopes_path).expanduser().read_text())
        except FileNotFoundError:
            pinned = []
        if not isinstance(pinned, list):
            raise ChatlogSourceError('scopes_invalid')
        known = {(x.get('account_id'), x.get('conversation_id')): x for x in pinned if isinstance(x, dict)}
        try:
            result = subprocess.run([str(self._verified_executable()), 'directory', '--source', 'wechat'],
                capture_output=True, text=True, timeout=self.config.timeout, check=False)
            directory = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            raise ChatlogSourceError('directory_unavailable') from error
        if result.returncode or not isinstance(directory, dict) or not directory.get('available'):
            raise ChatlogSourceError('directory_unavailable')
        scopes = []
        for item in directory.get('conversations', []):
            account, peer = item.get('account_id'), item.get('conversation_id')
            if not account or not peer:
                raise ChatlogSourceError('directory_invalid')
            if str(peer).endswith('@chatroom') or item.get('message_count') == 0:
                continue
            override = known.get((account, peer), {})
            scopes.append(dict(requested_id=peer, person_name=override.get('person_name') or item.get('remark') or item.get('label') or item.get('nickname') or peer,
                account_id=account, account_namespace=override.get('account_namespace') or self.config.account_namespace or account,
                conversation_id=peer, conversation_type='direct'))
        return sorted(scopes, key=lambda x: (x['account_id'], x['conversation_id']))

    def _window(self, state: dict[str, Any]) -> tuple[datetime, datetime]:
        """生成可重试的一天窗口；成功后再由 Connector 提交水位。"""

        now = datetime.now(UTC)
        previous = as_datetime(state.get('last_synced_at'))
        floor = self.config.since or as_datetime(state.get('enabled_since'))
        start = previous - timedelta(seconds=self.config.chatlog_overlap_seconds) if previous else (floor or now)
        if floor:
            start = max(floor, start)
        end = min(start + timedelta(seconds=self.config.chatlog_window_seconds), now)
        if self.config.until:
            end = min(end, self.config.until)
        return start, max(start, end)

    def _event(self, record: dict[str, Any], scope: dict[str, str]) -> dict[str, Any] | None:
        """保留源消息，不裁剪、改写或生成正文。"""

        occurred_at = as_datetime(record.get("ts"))
        if occurred_at is None or not isinstance(record.get("content"), str):
            raise ChatlogSourceError("invalid_record")
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
        message_key = None
        server_id = str(record.get("server_id") or "").strip()
        if server_id and server_id != "0":
            # 同账号两台 Mac 的 rowid/shard 偏移不同；服务器消息 ID 才是跨设备身份。
            stable_identity = {
                "account": scope.get("account_namespace") or scope["account_id"],
                "conversation": scope["conversation_id"],
                "server_id": server_id,
            }
            message_key = hashlib.sha256(
                json.dumps(stable_identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
        direction = "outbound" if record.get("is_self") is True else "inbound"
        return {
            "id": event_id,
            "_media_account_id": scope["account_id"],
            "source_message_key": message_key,
            "contact": scope["person_name"],
            "wxid": scope["requested_id"],
            "timestamp": occurred_at.isoformat(),
            "direction": direction,
            "message_type": str(record.get("msg_type") or "消息"),
            "content": record["content"],
            "message": {
                "account_namespace": scope.get("account_namespace") or scope["account_id"],
                "conversation_id": scope["conversation_id"],
                "conversation_type": scope["conversation_type"],
                **({"directory_conversation_type": scope["directory_conversation_type"]} if "directory_conversation_type" in scope else {}),
                "record": record,
            },
        }

    def read(self, state: dict[str, Any]) -> SourceBatch:
        """按源协议的 128 会话上限读取；全部完成才允许提交水位。"""

        executable = self._verified_executable()
        scopes = self._scopes()
        start, end = self._window(state)
        events: list[dict[str, Any]] = []
        for offset in range(0, len(scopes), 128):
            events.extend(self._read_chunk(executable, scopes[offset:offset + 128], start, end))
        return SourceBatch(events=events, until=end)

    def _read_chunk(self, executable: Path, scopes: list[dict[str, str]], start: datetime, end: datetime) -> list[dict[str, Any]]:
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
        return events
