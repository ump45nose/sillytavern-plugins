from datetime import date, timedelta


def assemble(source, period, now):
    if source is None:
        return None
    today = now.date()
    length = {"day": 1, "week": 7, "month": 30, "year": 371}[period]
    start = today - timedelta(days=length - 1)
    if period == "year":
        start = today - timedelta(days=today.weekday() + 52 * 7)
    def value(day, field):
        if day > today:
            return None
        if day == today:
            return source["today"].get(field)
        return source["daily"].get(day.isoformat(), {}).get(field)
    def total(first, last, field):
        values = [value(first + timedelta(days=i), field) for i in range((last-first).days + 1)]
        return sum(values) if values and all(v is not None for v in values) else None
    actual_length = (today-start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=actual_length-1)
    tools = source["tools"] if period == "day" else None
    devices = source["devices"] if period == "day" else None
    if period == "day":
        buckets = {"unit": "hour", "rows": "tool", "series": [{"key": t["id"], "values": [None] * 24} for t in tools]}
    elif period == "week":
        buckets = {"unit": "hour", "rows": "date", "series": [{"key": (start + timedelta(days=i)).isoformat(), "values": [None] * 24} for i in range(7)]}
    elif period == "month":
        buckets = None  # stats has no historical per-tool attribution.
    else:
        buckets = {"unit": "day", "rows": "year", "series": [{"key": "year", "values": [value(start + timedelta(days=i), "total") for i in range(371)]}]}
    result = {"range": period, "period": {"start": start.isoformat(), "end": today.isoformat()},
              "total": total(start, today, "total"), "cost": total(start, today, "cost"),
              "previous": total(previous_start, previous_end, "total"), "tools": tools, "devices": devices,
              "buckets": buckets, "limits": source["limits"], "today": {**source["today"], "cost": round(source["today"]["cost"], 2) if source["today"].get("cost") is not None else None}}
    if result["cost"] is not None:
        result["cost"] = round(result["cost"], 2)
    return result
