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
    days = [start+timedelta(days=i) for i in range(actual_length)]
    def parts(field):
        if period == 'day':
            return source.get(field)
        rows = [source.get(field) if day == today else source['daily'].get(day.isoformat(), {}).get(field) for day in days]
        if any(row is None for row in rows):
            return None
        merged = {}
        for row in rows:
            for item in row:
                current = merged.setdefault(item['id'], {**item, 'total': 0, 'cost': 0})
                for key in ('total', 'cost'):
                    current[key] = current[key]+item[key] if current[key] is not None and item.get(key) is not None else None
        return list(merged.values())
    def ordered(rows):
        return sorted(rows, key=lambda r: (r.get('total') is None, -(r.get('total') or 0), r['id'])) if rows is not None else None
    tools = ordered(parts('tools'))
    models = ordered(parts('models'))
    devices = source['devices']
    if period != 'day':
        histories = source.get('device_daily', {})
        interval_devices = []
        for device in devices:
            row = {**device}
            for field in ('total', 'cost'):
                values = [device.get(field) if day == today else
                          histories.get(device['id'], {}).get(day.isoformat(), {}).get(field) for day in days]
                row[field] = sum(values) if all(v is not None for v in values) else None
            interval_devices.append(row)
        devices = interval_devices if histories else None
    devices = ordered(devices)
    if period == "day":
        buckets = {"unit": "hour", "rows": "tool", "series": [{"key": t["id"], "values": [None] * 24} for t in tools]} if tools is not None else None
    elif period == "week":
        buckets = {"unit": "hour", "rows": "date", "series": [{"key": (start + timedelta(days=i)).isoformat(), "values": [None] * 24} for i in range(7)]}
    elif period == "month":
        buckets = None  # Preserve the existing month bucket shape; v2 uses history/parts.
    else:
        buckets = {"unit": "day", "rows": "year", "series": [{"key": "year", "values": [value(start + timedelta(days=i), "total") for i in range(371)]}]}
    result = {"range": period, "period": {"start": start.isoformat(), "end": today.isoformat()},
              "total": total(start, today, "total"), "cost": total(start, today, "cost"),
              "previous": total(previous_start, previous_end, "total"), "tools": tools, "devices": devices,
              'models': models,
              'history': [{'date': day, 'total': row.get('total'), 'cost': row.get('cost')} for day, row in sorted(source['daily'].items()) if day <= today.isoformat()],
              'sessions': source.get('sessions', {}).get('day') if period == 'day' else
                          source.get('sessions', {}).get('calendar_month') if start == today.replace(day=1) else None,
              "buckets": buckets, "limits": source["limits"], "today": {**source["today"], "cost": round(source["today"]["cost"], 2) if source["today"].get("cost") is not None else None}}
    if result["cost"] is not None:
        result["cost"] = round(result["cost"], 2)
    return result
