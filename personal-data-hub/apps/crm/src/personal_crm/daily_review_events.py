"""每日 23:00 产出私有日报快照，经现有 MCP Events 队列定时推送。"""

from __future__ import annotations

import asyncio
import fcntl
import hmac
import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from personal_crm.core.domain import ensure_utc, utcnow
from personal_crm.daily_review import SOURCES, content_page, report_page

EVENT_NAMES = {
    "codex_skylight": "crm.daily_codex_skylight.ready",
}


class DailyReviewEventProducer:
    def __init__(
        self,
        service,
        events,
        *,
        source: str,
        owner: str,
        storage_path: str,
        timezone: str = "Asia/Shanghai",
        send_time: str = "23:00",
        poll_seconds: int = 60,
    ):
        if source not in SOURCES:
            raise ValueError("unknown daily review source")
        if not owner or owner != owner.strip():
            raise ValueError("daily review event owner is required")
        if not re.fullmatch(r"\d{2}:\d{2}", send_time):
            raise ValueError("daily review event time must be HH:MM")
        self.send_time = time(*map(int, send_time.split(":")))
        self.zone = ZoneInfo(timezone)
        self.service, self.events, self.source, self.owner = service, events, source, owner
        self.poll_seconds = max(10, poll_seconds)
        self.directory = Path(storage_path) / source
        self.reports = self.directory / "reports"
        for path in (Path(storage_path), self.directory, self.reports):
            if path.is_symlink():
                raise ValueError("daily review event storage must not be a symlink")
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)
        self._async_lock = asyncio.Lock()
        fields = {
            "source": {"type": "string", "enum": [source]},
            "report_id": {"type": "string"},
            "date": {"type": "string"},
            "timezone": {"type": "string"},
            "generated_at": {"type": "string"},
            "scheduled_at": {"type": "string"},
            "total_count": {"type": "integer", "minimum": 0},
            "empty_day": {"type": "boolean"},
            "summary_type": {"type": "string"},
            "read_tool": {"type": "string"},
            "read_arguments": {"type": "object"},
        }
        events.register_event(
            EVENT_NAMES[source],
            '每日已同步的 Codex Skylight 摘要快照，可分页读取上游正文。',
            {"type": "object", "properties": {}, "additionalProperties": False},
            {
                "type": "object",
                "properties": fields,
                "required": [key for key in fields if key != "summary_type"],
                "additionalProperties": False,
            },
            subjects={owner},
        )

    @contextmanager
    def _locked(self):
        fd = os.open(self.directory / "producer.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _write(path: Path, value: dict):
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _state(self):
        path = self.directory / "state.json"
        if not path.exists():
            return None
        state = json.loads(path.read_text(encoding="utf-8"))
        if (
            state.get("version") != 1
            or state.get("owner") != self.owner
            or state.get("source") != self.source
            or state.get("timezone") != self.zone.key
        ):
            raise ValueError("daily review event state identity or timezone mismatch")
        return state

    def _load_report(self, report_id: str):
        if not re.fullmatch(r"[a-f0-9]{32}", report_id):
            raise ValueError("invalid report id")
        path = self.reports / (report_id + ".json")
        if path.is_symlink():
            raise ValueError("invalid report storage")
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ValueError("report not found") from None
        if report.get("owner") != self.owner or report["metadata"]["source"] != self.source:
            raise PermissionError("report access denied")
        return report

    def _prepare(self, now: datetime):
        with self._locked():
            state = self._state()
            if state is None:
                state = {
                    "version": 1,
                    "owner": self.owner,
                    "source": self.source,
                    "timezone": self.zone.key,
                    "next_day": now.astimezone(self.zone).date().isoformat(),
                    "pending_report": None,
                }
                self._write(self.directory / "state.json", state)
            if state["pending_report"]:
                return self._load_report(state["pending_report"])
            day = date.fromisoformat(state["next_day"])
            due = datetime.combine(day, self.send_time, self.zone)
            if now < due:
                return None
            report = self.service.snapshot(self.source, day.isoformat(), self.zone.key)
            report_id = uuid5(
                NAMESPACE_URL, f"crm-daily-review:{self.owner}:{self.source}:{self.zone.key}:{day}"
            ).hex
            report["owner"] = self.owner
            report["metadata"].update(
                {
                    "report_id": report_id,
                    "generated_at": now.isoformat(),
                    "scheduled_at": due.isoformat(),
                    "read_tool": "get_daily_review_event_report",
                    "read_arguments": {"source": self.source, "report_id": report_id},
                }
            )
            self._write(self.reports / (report_id + ".json"), report)
            state["pending_report"] = report_id
            self._write(self.directory / "state.json", state)
            return report

    def _commit(self, report: dict):
        with self._locked():
            state = self._state()
            if state["pending_report"] != report["metadata"]["report_id"]:
                return
            state["next_day"] = (
                date.fromisoformat(report["metadata"]["date"]) + timedelta(days=1)
            ).isoformat()
            state["pending_report"] = None
            self._write(self.directory / "state.json", state)

    async def run_once(self, now: datetime | None = None):
        async with self._async_lock:
            report = await asyncio.to_thread(self._prepare, ensure_utc(now or utcnow()))
            if report is None:
                return None
            metadata = report["metadata"]
            delivery = await self.events.publish(
                EVENT_NAMES[self.source],
                metadata,
                subject=self.owner,
                event_id="crm-daily-review-" + metadata["report_id"],
                timestamp=metadata["generated_at"],
            )
            await asyncio.to_thread(self._commit, report)
            return {"report_id": metadata["report_id"], "delivery": delivery}

    async def serve(self):
        while True:
            try:
                await self.run_once()
            except Exception as error:
                logging.getLogger(__name__).error(
                    "CRM daily review event %s failed (%s)", self.source, type(error).__name__
                )
            await asyncio.sleep(self.poll_seconds)

    def _authorized_report(self, report_id: str, subject: str):
        if not isinstance(subject, str) or not hmac.compare_digest(
            subject.encode(), self.owner.encode()
        ):
            raise PermissionError("report access denied")
        return self._load_report(report_id)

    def read_page(self, report_id: str, *, subject: str, offset: int = 0, limit: int = 20):
        report = self._authorized_report(report_id, subject)
        return report_page(report["metadata"], report["records"], offset, limit)

    def read_content(
        self, report_id: str, record_id: str, *, subject: str, offset: int = 0, limit: int = 12000
    ):
        report = self._authorized_report(report_id, subject)
        return {
            **report["metadata"],
            **content_page(report["records"], record_id, offset, limit),
        }


def register_daily_review_event_tools(server, producers: dict, *, auth):
    def producer(source: str):
        if source not in producers:
            raise ValueError("unknown daily review event source")
        return producers[source]

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_daily_review_event_report(
        source: str, report_id: str, offset: int = 0, limit: int = 20
    ) -> dict:
        """分页读取每日事件冻结的 Skylight 摘要正文，仅报告所有者可读。"""
        selected = producer(source)
        return selected.read_page(
            report_id, subject=selected.events.authenticated_subject(), offset=offset, limit=limit
        )

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_daily_review_event_content(
        source: str, report_id: str, record_id: str, offset: int = 0, limit: int = 12000
    ) -> dict:
        """续读每日事件快照的单条长正文，保留原文每个字符。"""
        selected = producer(source)
        return selected.read_content(
            report_id,
            record_id,
            subject=selected.events.authenticated_subject(),
            offset=offset,
            limit=limit,
        )
