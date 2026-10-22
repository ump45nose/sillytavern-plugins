"""Read-only Personal Records adapter. Never uses webhook or write credentials."""
import asyncio
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal

from .base import Adapter


def union_seconds(intervals):
    pairs = sorted((datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp(),
                    datetime.fromisoformat(e.replace("Z", "+00:00")).timestamp()) for s, e in intervals)
    end = float("-inf")
    total = 0
    for start, stop in pairs:
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def intervals(samples):
    return [(s["start"], s["end"]) for s in samples]


def health_day(record):
    sleep = record.get("sleep")
    asleep = [s for s in sleep or [] if s["stage"] in ("sleeping", "light", "deep", "rem")]
    awake = [s for s in sleep or [] if s["stage"] in ("awake", "awake_in_bed", "out_of_bed")]
    duration = (union_seconds(intervals(asleep + awake)) - union_seconds(intervals(awake))) / 60 if asleep else None
    stages = []
    for target, names in {"deep": ("deep",), "core": ("light",), "rem": ("rem",),
                          "awake": ("awake", "awake_in_bed", "out_of_bed")}.items():
        samples = [s for s in sleep or [] if s["stage"] in names]
        if samples:
            stages.append({"stage": target, "minutes": round(union_seconds(intervals(samples)) / 60, 2)})
    def latest(field, value):
        samples = record.get(field) or []
        return max(samples, key=lambda s: s["time"])[value] if samples else None
    exercise = record.get("exercise")
    return {"date": record["date"], "steps": record.get("steps"),
            "active_kcal": record.get("active_calories_kcal"),
            "exercise_minutes": round(union_seconds(intervals(exercise)) / 60, 2) if exercise else None,
            "sleep_minutes": round(duration, 2) if duration is not None else None,
            "sleep_stages": stages if sleep else None,
            "resting_hr": latest("resting_heart_rate", "bpm"), "spo2": latest("oxygen_saturation", "percentage")}


class Records:
    def __init__(self, client, settings, now):
        self.client, self.settings, self.now = client, settings, now
        self.slots = asyncio.Semaphore(4)

    async def get(self, path, params=None, missing=False):
        async with self.slots:
            response = await self.client.get(self.settings.records_url.rstrip("/") + "/api/v1/" + path,
                params=params, headers={"Authorization": "Bearer " + self.settings.records_token.get_secret_value()})
        if missing and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def health(self):
        today = self.now().date()
        days = [today - timedelta(days=d) for d in reversed(range(14))]
        # The source list endpoint contains scalar values and sample counts only.
        # Fetch the 14 known day keys, bounded to four simultaneous requests.
        records = await asyncio.gather(*(self.get("health/days/" + d.isoformat(), missing=True) for d in days))
        normalized = [health_day(r or {"date": d.isoformat()}) for d, r in zip(days, records)]
        current = normalized[-1]
        return {**current, "step_goal": 8600, "kcal_goal": 520, "exercise_goal": 45,
                "days": [{k: day[k] for k in ("date", "steps", "resting_hr", "sleep_minutes")} for day in normalized]}

    async def bills(self):
        today = self.now().date()
        month = today.replace(day=1)
        start = min(month, today - timedelta(days=13))
        filters = {"type": "expense", "currency": "CNY", "status": "confirmed"}
        days, categories = await asyncio.gather(
            self.get("bills/summary", {**filters, "start_date": start.isoformat(), "end_date": today.isoformat(), "group_by": "date"}),
            self.get("bills/summary", {**filters, "start_date": month.isoformat(), "end_date": today.isoformat(), "group_by": "category"}))
        rows, offset = [], 0
        while True:
            page = await self.get("bills", {**filters, "start_date": today.isoformat(), "end_date": today.isoformat(), "limit": 200, "offset": offset})
            rows.extend(page["records"])
            next_offset = page.get("next_offset")
            if next_offset is None:
                break
            if next_offset <= offset:
                raise ValueError("invalid source pagination")
            offset = next_offset
        totals = {r["date"]: Decimal(r["amount"]) for r in days["groups"]}
        # Successful exhaustive summaries establish zero expenditure on absent dates.
        month_total = sum((v for d, v in totals.items() if d >= month.isoformat()), Decimal(0))
        amount = lambda v: float(v.quantize(Decimal("0.01")))
        return {"date": today.isoformat(), "today_total": amount(totals.get(today.isoformat(), Decimal(0))),
                "month_total": amount(month_total), "month_budget": None,
                "days_left_in_month": calendar.monthrange(today.year, today.month)[1] - today.day,
                "today_items": [{"id": r["id"], "title": r.get("item") or r.get("merchant") or r.get("note"),
                    "category": r.get("category"), "time": datetime.fromisoformat(r["occurred_at"].replace("Z", "+00:00")).astimezone(self.now().tzinfo).isoformat(),
                    "amount": amount(Decimal(r["amount"]))} for r in rows],
                "days": [{"date": (d := today - timedelta(days=n)).isoformat(), "total": amount(totals.get(d.isoformat(), Decimal(0)))} for n in reversed(range(14))],
                "month_categories": [{"name": r["category"], "amount": amount(Decimal(r["amount"]))}
                                     for r in sorted(categories["groups"], key=lambda r: Decimal(r["amount"]), reverse=True)[:8]],
                "net_worth": None, "net_worth_months": None, "accounts": None}

    def adapters(self):
        configured = bool(self.settings.records_token)
        return [Adapter("records_health", "Personal Records · 健康", 60, self.health if configured else None),
                Adapter("records_bills", "Personal Records · 账单", 60, self.bills if configured else None)]
