from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .reports import ReportStore, atomic_json, build_report, summary


EVENT_NAME = "usage.daily_ready"
INPUT_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
PAYLOAD_SCHEMA = {
    "type": "object", "required": ["report_id", "date", "timezone", "generated_at", "summary"],
    "properties": {
        "report_id": {"type": "string"}, "date": {"type": "string", "format": "date"},
        "timezone": {"type": "string"}, "generated_at": {"type": "string", "format": "date-time"},
        "summary": {"type": "object"},
    }, "additionalProperties": False,
}


class DailyUsageProducer:
    def __init__(self, events, settings, builder=build_report):
        self.events, self.settings, self.builder = events, settings, builder
        self.store = ReportStore(settings.data_dir)
        self.state_file = Path(settings.data_dir) / "daily-state.json"
        self.subject = settings.event_subject

    def register(self):
        self.events.register_event(
            EVENT_NAME, "每天 23:00（Asia/Taipei）生成当天截至生成时的 Token Monitor 与 ShellCrash 数据；事件含摘要与报告 ID。",
            INPUT_SCHEMA, PAYLOAD_SCHEMA, subjects={self.subject} if self.subject else None)

    def status(self):
        state = {}
        if self.state_file.is_file():
            with self.state_file.open() as handle:
                state = json.load(handle)
        return {"enabled": self.settings.events_enabled, "timezone": self.settings.timezone,
                "daily_time": f"{self.settings.schedule_hour:02d}:{self.settings.schedule_minute:02d}",
                "last_report_date": state.get("last_report_date"), "last_event_id": state.get("last_event_id"),
                "scope": "当日 00:00 至生成时；重启仅补当天到期日报，不回放历史。"}

    async def run_once(self, now=None):
        if not self.settings.events_enabled:
            return {"status": "disabled"}
        now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(self.settings.timezone))
        due = now.replace(hour=self.settings.schedule_hour, minute=self.settings.schedule_minute, second=0, microsecond=0)
        if now < due:
            return {"status": "not_due"}
        day = now.date().isoformat()
        if self.status().get("last_report_date") == day:
            return {"status": "already_queued", "date": day}
        report = self.store.get("usage-" + day)
        if report is None:
            report = await asyncio.to_thread(self.builder, self.settings, day, now)
            report = await asyncio.to_thread(self.store.save_once, report)
        # The archived report is immutable, so crash/retry keeps both ID and payload.
        event_id = EVENT_NAME + ":" + day
        payload = {"report_id": report["report_id"], "date": day, "timezone": self.settings.timezone,
                   "generated_at": report["window"]["generated_at"], "summary": summary(report, top=3)}
        result = await self.events.publish(EVENT_NAME, payload, subject=self.subject,
                                           event_id=event_id, timestamp=payload["generated_at"])
        atomic_json(self.state_file, {"last_report_date": day, "last_event_id": event_id})
        return {"status": "queued", "date": day, "event_id": event_id,
                "queued": result.get("queued"), "duplicate": result.get("duplicate")}

    async def serve(self):
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logging.getLogger(__name__).warning("usage daily producer failed: %s", type(error).__name__)
            await asyncio.sleep(30)
