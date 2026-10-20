from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as Date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def instant(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result if result.tzinfo is not None else None
    except ValueError:
        return None


def day_bounds(day: Date, zone: str):
    tz = ZoneInfo(zone)
    return datetime.combine(day, time.min, tz), datetime.combine(day + timedelta(days=1), time.min, tz)


@dataclass(frozen=True)
class Window:
    day: Date
    timezone: str
    start: datetime
    end: datetime
    day_end: datetime
    generated_at: datetime

    @classmethod
    def make(cls, day: str | None = None, zone: str = "Asia/Taipei", now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("生成时间必须包含时区")
        local_now = now.astimezone(ZoneInfo(zone))
        if day is not None and (not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)):
            raise ValueError("日期必须为 YYYY-MM-DD")
        target = Date.fromisoformat(day) if day is not None else local_now.date()
        if target > local_now.date():
            raise ValueError("不能读取未来日期")
        start, end = day_bounds(target, zone)
        return cls(target, zone, start, min(end, local_now), end, local_now)

    def metadata(self):
        return {
            "date": self.day.isoformat(),
            "timezone": self.timezone,
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "calendar_day_end": self.day_end.isoformat(),
            "is_partial_day": self.end < self.day_end,
            "generated_at": self.generated_at.isoformat(),
        }
