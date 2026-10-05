from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .client import ReadOnlyMCPClient, SourceError


TZ = ZoneInfo("Asia/Taipei")
UTC = timezone.utc
PAGE_SIZE = 20
EVENTS = {
    "dingtalk.todo.assigned": "有待办新分配给当前用户",
    "dingtalk.todo.changed": "当前用户待办的标题、截止时间或优先级变化",
    "dingtalk.todo.due": "待办进入未来24小时到期范围或首次逾期",
    "dingtalk.approval.pending": "当前用户有新待处理审批",
    "dingtalk.calendar.changed": "当前用户主日历近期日程新增或关键内容变化",
}
PAYLOAD_SCHEMA = {
    "type": "object",
    "properties": {
        "event_id": {"type": "string"},
        "source": {"type": "string"},
        "record_id": {"type": "string"},
        "title": {"type": "string"},
        "reason": {"type": "string"},
        "detected_at": {"type": "string"},
        "timezone": {"type": "string"},
        "record": {"type": "object"},
        "transport": {"type": "string", "const": "read_only_polling"},
    },
    "required": ["event_id", "source", "record_id", "detected_at", "transport"],
    "additionalProperties": False,
}


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _stamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timezone_required")
    return value.astimezone(TZ).isoformat()


def _first(record: dict, *keys: str) -> Any:
    return next((record[k] for k in keys if record.get(k) is not None), None)


def _string(value: Any, max_length: int = 1000) -> str:
    return "" if value is None else str(value)[:max_length]


def _time(value: Any) -> str | None:
    if value in (None, "", 0, "0", -1, "-1"):
        return None
    try:
        if isinstance(value, dict):
            value = value.get("dateTime") or value.get("date")
        if isinstance(value, (int, float)) or str(value).isdigit():
            numeric = float(value)
            return _stamp(datetime.fromtimestamp(numeric / (1000 if numeric > 10**11 else 1), UTC))
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TZ)
        return _stamp(parsed)
    except (ValueError, TypeError, OverflowError, OSError):
        raise SourceError("invalid_record_time") from None


def _safe_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme in {"dingtalk", "dtx"}:
        return value[:4096]
    if parsed.scheme == "https" and parsed.hostname and (
        parsed.hostname == "dingtalk.com" or parsed.hostname.endswith(".dingtalk.com")
    ):
        return value[:4096]
    return None


def normalize(source: str, row: dict) -> dict:
    if not isinstance(row, dict):
        raise SourceError("invalid_record_shape")
    if source == "todo":
        record_id = _first(row, "taskId", "task_id")
        title = _first(row, "subject", "title")
        if record_id is None or not title:
            raise SourceError("todo_record_schema_changed")
        return {
            "id": str(record_id), "title": _string(title),
            "due_at": _time(_first(row, "dueTime", "planFinishDate")),
            "priority": row.get("priority"),
            "created_at": _time(row.get("createdTime")),
        }
    if source == "approval":
        task_id = _first(row, "taskId", "task_id", "id")
        instance_id = _first(row, "processInstanceId", "process_instance_id", "instanceId")
        if task_id is None and instance_id is None:
            raise SourceError("approval_record_schema_changed")
        return {
            "id": ":".join(str(v) for v in (instance_id, task_id) if v is not None),
            "task_id": _string(task_id), "process_instance_id": _string(instance_id),
            "title": _string(_first(row, "title", "processTitle", "processName", "name")),
            "url": _safe_url(_first(row, "url", "taskUrl", "processInstanceUrl", "process_instance_url")),
            "created_at": _time(_first(row, "createTime", "create_time", "createdTime")),
        }
    if source == "calendar":
        record_id = _first(row, "eventId", "id")
        if record_id is None:
            raise SourceError("calendar_record_schema_changed")
        return {
            "id": str(record_id), "title": _string(_first(row, "summary", "subject", "title")),
            "start_at": _time(_first(row, "start", "startTime")),
            "end_at": _time(_first(row, "end", "endTime")),
            "location": row.get("location"), "status": row.get("status"),
        }
    raise SourceError("unknown_source")


def _due_level(record: dict, now: datetime) -> str:
    if not record.get("due_at"):
        return "none"
    delta = datetime.fromisoformat(record["due_at"]) - now
    return "overdue" if delta.total_seconds() < 0 else "due_soon" if delta <= timedelta(hours=24) else "none"


def _fingerprint(source: str, record: dict) -> str:
    fields = {
        "todo": ("title", "due_at", "priority"),
        "approval": ("task_id", "process_instance_id", "title"),
        "calendar": ("title", "start_at", "end_at", "location", "status"),
    }[source]
    return _hash({k: record.get(k) for k in fields})


def load_config(path: Path) -> dict:
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("dingtalk_config_requires_mode_600")
    config = json.loads(path.read_text())
    subject = config.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("dingtalk_subject_required")
    sources = config.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("dingtalk_sources_required")
    for key, source in sources.items():
        if key not in {"todo", "approval", "calendar"} or not isinstance(source, dict):
            raise ValueError("dingtalk_source_invalid")
        if not isinstance(source.get("enabled", True), bool):
            raise ValueError("dingtalk_source_enabled_must_be_boolean")
        if not source.get("enabled", True) and not source.get("url"):
            continue
        headers = source.get("headers", {})
        if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()):
            raise ValueError("dingtalk_upstream_headers_invalid")
        parsed = urlsplit(source.get("url", ""))
        if parsed.scheme != "https" or parsed.hostname != "mcp-gw.dingtalk.com" or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("dingtalk_official_upstream_required")
    interval = config.get("poll_interval_seconds", 300)
    if not isinstance(interval, int) or not 60 <= interval <= 3600:
        raise ValueError("dingtalk_poll_interval_invalid")
    return config


class DingTalkProducer:
    def __init__(self, events, *, config: dict, storage_path: str | Path, client=None):
        self.events, self.config = events, config
        self.subject = config["subject"]
        self.sources = config["sources"]
        self.client = client or ReadOnlyMCPClient(self.sources)
        self.poll_interval = config.get("poll_interval_seconds", 300)
        self.directory = Path(storage_path)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "state.json"
        self.credential_epoch = _hash({"subject": self.subject, "sources": {
            key: {"url": source.get("url"), "headers": source.get("headers", {})}
            for key, source in self.sources.items()
        }})
        self.state = self._load()
        self.lock = asyncio.Lock()
        self.worker_error = None

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "epoch": self.credential_epoch, "sources": {}, "pending": [], "recent": []}
        loaded = json.loads(self.path.read_text())
        if loaded.get("version") != 1 or any(k not in loaded for k in ("epoch", "sources", "pending", "recent")):
            raise ValueError("dingtalk_state_invalid")
        if loaded["epoch"] != self.credential_epoch:
            # Credential/account changes require an explicit, reviewable baseline reset.
            raise ValueError("dingtalk_source_binding_changed")
        return loaded

    def _save(self):
        raw = json.dumps(self.state, ensure_ascii=False, separators=(",", ":"))
        target = self.directory / "state.json.tmp"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(target, self.path)
        os.chmod(self.path, 0o600)

    def register(self):
        for name, description in EVENTS.items():
            source = name.split(".")[1]
            if source not in self.sources or not self.sources[source].get("enabled", True):
                continue
            self.events.register_event(
                name, description,
                {"type": "object", "properties": {}, "additionalProperties": False},
                PAYLOAD_SCHEMA,
            )

    async def _fetch(self, source: str, now: datetime) -> list[dict]:
        records: dict[str, dict] = {}
        cursor = None
        async with self.client.session(source) as call:
            for page in range(1, 101):
                if source == "todo":
                    args = {"pageNum": str(page), "pageSize": str(PAGE_SIZE), "roleTypes": ["executor"], "todoStatus": "false"}
                    key = "todoCards"
                elif source == "approval":
                    # Omitting userId preserves the authenticated upstream account;
                    # no create-time filter omits old approvals awaiting a new step.
                    args = {"pageNumber": page, "pageSize": PAGE_SIZE}
                    key = "values"
                else:
                    day = now.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
                    args = {"calendarId": self.sources[source]["calendar_id"], "limit": PAGE_SIZE,
                            "startTime": int(day.timestamp() * 1000), "endTime": int((day + timedelta(days=14)).timestamp() * 1000)}
                    if cursor:
                        args["cursor"] = cursor
                    key = "events"
                response = await call(args)
                rows = response.get(key)
                if not isinstance(rows, list):
                    raise SourceError(source + "_list_schema_changed")
                for row in rows:
                    record = normalize(source, row)
                    previous = records.get(record["id"])
                    if previous is not None and previous != record:
                        raise SourceError("inconsistent_page_snapshot")
                    records[record["id"]] = record
                has_more = response.get("hasMore", response.get("has_more"))
                if has_more is not None and not isinstance(has_more, bool):
                    raise SourceError("pagination_schema_changed")
                if has_more is False:
                    return list(records.values())
                if has_more is None and len(rows) < PAGE_SIZE:
                    return list(records.values())
                if not rows:
                    raise SourceError("pagination_stalled")
                if source == "calendar":
                    next_cursor = response.get("nextCursor", response.get("cursor"))
                    if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                        raise SourceError("pagination_stalled")
                    cursor = next_cursor
        raise SourceError("pagination_limit_reached")

    def _event(self, name: str, source: str, record: dict, reason: str, revision: int, now: datetime) -> dict:
        event_id = "dd-" + _hash([self.credential_epoch, name, record["id"], revision])[:48]
        payload = {
            "event_id": event_id, "source": source, "record_id": record["id"],
            "title": record.get("title", ""), "reason": reason,
            "detected_at": _stamp(now), "timezone": "Asia/Taipei", "record": record,
            "transport": "read_only_polling",
        }
        return {"event_id": event_id, "name": name, "data": payload, "timestamp": _stamp(now)}

    def _ingest(self, source: str, records: list[dict], now: datetime):
        previous = self.state["sources"].get(source, {})
        baseline = not previous.get("initialized", False)
        known = copy.deepcopy(previous.get("records", {}))
        active_ids = {record["id"] for record in records}
        for record in records:
            record_id = record["id"]
            old = known.get(record_id)
            fingerprint = _fingerprint(source, record)
            level = _due_level(record, now) if source == "todo" else "none"
            revision = old.get("revision", 0) if old else 0
            name = reason = None
            if not baseline:
                if old is None or not old.get("active", False):
                    name = {"todo": "dingtalk.todo.assigned", "approval": "dingtalk.approval.pending", "calendar": "dingtalk.calendar.changed"}[source]
                    reason = "new_assignment" if old is None else "returned_to_pending"
                    if source == "calendar":
                        reason = "new_calendar_item"
                elif fingerprint != old["fingerprint"]:
                    if source == "todo":
                        name, reason = "dingtalk.todo.changed", "important_fields_changed"
                    elif source == "calendar":
                        name, reason = "dingtalk.calendar.changed", "important_fields_changed"
                elif source == "todo" and level != old.get("due_level", "none") and level != "none":
                    name, reason = "dingtalk.todo.due", level
            if name:
                revision += 1
                self.state["pending"].append(self._event(name, source, record, reason, revision, now))
            known[record_id] = {"record": record, "fingerprint": fingerprint, "due_level": level,
                                "revision": revision, "active": True, "last_seen_at": _stamp(now)}
        for record_id, item in known.items():
            if record_id not in active_ids:
                item["active"] = False
        cutoff = now - timedelta(days=180)
        known = {k: v for k, v in known.items() if v["active"] or datetime.fromisoformat(v["last_seen_at"]) >= cutoff}
        self.state["sources"][source] = {
            "initialized": True, "records": known, "status": "ready", "active_count": len(records),
            "last_attempt_at": _stamp(now), "last_success_at": _stamp(now), "error": None,
            "consecutive_failures": 0, "next_poll_at": _stamp(now + timedelta(seconds=self.poll_interval)),
        }
        self._save()

    async def _flush(self):
        while self.state["pending"]:
            pending = self.state["pending"][0]
            await self.events.publish(
                pending["name"], pending["data"], subject=self.subject,
                event_id=pending["event_id"], timestamp=pending["timestamp"],
            )
            self.state["recent"].append(pending)
            self.state["recent"] = self.state["recent"][-200:]
            del self.state["pending"][0]
            self._save()

    async def poll_once(self, *, now: datetime | None = None, force: bool = False) -> dict:
        now = now or datetime.now(UTC)
        _stamp(now)
        async with self.lock:
            await self._flush()
            for source, config in self.sources.items():
                if not config.get("enabled", True):
                    continue
                current = self.state["sources"].get(source, {})
                if not force and current.get("next_poll_at") and datetime.fromisoformat(current["next_poll_at"]) > now:
                    continue
                try:
                    rows = await self._fetch(source, now)
                    self._ingest(source, rows, now)
                except asyncio.CancelledError:
                    raise
                except SourceError as error:
                    current = self.state["sources"].setdefault(source, {})
                    failures = current.get("consecutive_failures", 0) + 1
                    current.update(status="degraded", last_attempt_at=_stamp(now), error=str(error), consecutive_failures=failures,
                                   next_poll_at=_stamp(now + timedelta(seconds=min(3600, self.poll_interval * 2 ** min(failures - 1, 4)))))
                    self._save()
            await self._flush()
            self.worker_error = None
            return self.status(subject=self.subject)

    async def serve(self):
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                # Preserve queued events. A delivery/storage failure must not reset
                # the baseline or expose upstream credentials in a traceback.
                self.worker_error = type(error).__name__
                await asyncio.sleep(30)
            await asyncio.sleep(15)

    def _authorize(self, subject: str):
        if subject != self.subject:
            raise PermissionError("dingtalk_subject_mismatch")

    def status(self, *, subject: str) -> dict:
        self._authorize(subject)
        sources = {}
        for name, config in self.sources.items():
            current = self.state["sources"].get(name, {})
            sources[name] = {k: current.get(k) for k in ("initialized", "status", "active_count", "last_attempt_at", "last_success_at", "error", "next_poll_at")}
            if not config.get("enabled", True):
                sources[name].update(status="disabled", error=config.get("disabled_reason", "disabled_by_config"))
        return {"transport": "read_only_polling", "poll_interval_seconds": self.poll_interval,
                "timezone": "Asia/Taipei", "sources": sources, "pending_events": len(self.state["pending"]),
                "retained_events": len(self.state["recent"]), "history_replayed": False,
                "worker_error": self.worker_error}

    def list_recent(self, *, subject: str, limit: int = 20) -> dict:
        self._authorize(subject)
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit_must_be_1_to_200")
        return {"events": copy.deepcopy(list(reversed(self.state["recent"][-limit:])))}

    def detail(self, event_id: str, *, subject: str) -> dict:
        self._authorize(subject)
        for event in reversed(self.state["recent"] + self.state["pending"]):
            if event["event_id"] == event_id:
                return copy.deepcopy(event)
        raise ValueError("dingtalk_event_not_found")


def build_producer(events, *, config_path: str | Path, storage_path: str | Path) -> DingTalkProducer:
    return DingTalkProducer(events, config=load_config(Path(config_path)), storage_path=storage_path)
