"""One query and aggregation implementation for HTTP, MCP, and migration audit."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, localcontext

from .models import ASLEEP, BILL_TYPES, HEALTH_FIELDS, POINTS, SCALARS, SERIES, business_day, date_window, day, instant
from .store import Store


def pagination(offset, limit):
    if isinstance(offset, bool) or isinstance(limit, bool) or not isinstance(offset, int) or not isinstance(limit, int) or offset < 0 or not 1 <= limit <= 200:
        raise ValueError("offset must be nonnegative and limit must be 1..200")


def health_range(start_date=None, end_date=None):
    clauses, args = [], []
    if start_date:
        clauses.append("date>=?"); args.append(day(start_date))
    if end_date:
        clauses.append("date<=?"); args.append(day(end_date))
    if start_date and end_date:
        date_window(start_date, end_date)
    return " WHERE " + " AND ".join(clauses) if clauses else "", args


def union_seconds(intervals):
    merged = []
    for start, end in sorted((instant(a), instant(b)) for a, b in intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return sum((end-start).total_seconds() for start, end in merged)


class Service:
    def __init__(self, store: Store):
        self.store = store

    def create_health_day(self, record: dict): return self.store.create_health(record)
    def get_health_day(self, selected: str): return self.store.get_health(selected)
    def update_health_day(self, selected: str, patch: dict): return self.store.update_health(selected, patch)
    def delete_health_day(self, selected: str): return self.store.delete_health(selected)
    def create_bill(self, record: dict): return self.store.create_bill(record)
    def get_bill(self, identifier: str): return self.store.get_bill(identifier)
    def update_bill(self, identifier: str, patch: dict): return self.store.update_bill(identifier, patch)
    def delete_bill(self, identifier: str): return self.store.delete_bill(identifier)

    def list_health_days(self, start_date=None, end_date=None, offset=0, limit=50):
        pagination(offset, limit)
        where, args = health_range(start_date, end_date)
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM health_days" + where + " ORDER BY date DESC LIMIT ? OFFSET ?", [*args, limit+1, offset]).fetchall()
        records = []
        for row in rows[:limit]:
            data = json.loads(row["data"])
            records.append({"date": row["date"], "updated_at": row["updated_at"],
                **{key: data[key] for key in SCALARS if key in data},
                "sample_counts": {key: len(data[key]) for key in SERIES if key in data}})
        return {"records": records, "next_offset": offset+limit if len(rows) > limit else None}

    def health_summary(self, start_date: str, end_date: str, metrics: list[str] | None = None):
        date_window(start_date, end_date)
        selected = HEALTH_FIELDS if metrics is None else tuple(metrics)
        if not selected or not set(selected) <= set(HEALTH_FIELDS):
            raise ValueError("unknown or empty health metrics")
        scalars = {key: {"total": 0, "days": 0} for key in SCALARS if key in selected}
        points = {key: {"sample_count": 0, "sum": 0, "min": None, "max": None, "latest": None} for key in POINTS if key in selected}
        intervals = {key: [] for key in ("sleep", "exercise") if key in selected}
        # Stream the requested days; time-series arrays are never loaded for the entire archive.
        covered = 0
        with self.store.connection() as db:
            for row in db.execute("SELECT data FROM health_days WHERE date>=? AND date<=? ORDER BY date", (start_date, end_date)):
                covered += 1
                data = json.loads(row["data"])
                for key in scalars:
                    if key in data:
                        scalars[key]["total"] += data[key]
                        scalars[key]["days"] += 1
                for key in points:
                    stats = points[key]
                    for sample in data.get(key, []):
                        value = sample[POINTS[key]]
                        stats["sample_count"] += 1
                        stats["sum"] += value
                        stats["min"] = value if stats["min"] is None else min(stats["min"], value)
                        stats["max"] = value if stats["max"] is None else max(stats["max"], value)
                        if stats["latest"] is None or sample["time"] >= stats["latest"]["time"]:
                            stats["latest"] = sample
                for key in intervals:
                    intervals[key].extend(data.get(key, []))
        result = {}
        for key, value in scalars.items():
            result[key] = {"total": value["total"] if value["days"] else None, "days": value["days"]}
        for key, value in points.items():
            total = value.pop("sum")
            result[key] = {**value, "average": round(total/value["sample_count"], 2) if value["sample_count"] else None}
        for key, samples in intervals.items():
            item = {"sample_count": len(samples), "duration_seconds": union_seconds((s["start"], s["end"]) for s in samples) if samples else None}
            if key == "sleep":
                asleep = [s for s in samples if s["stage"] in ASLEEP]
                awake = [s for s in samples if s["stage"] in ("awake", "awake_in_bed", "out_of_bed")]
                item["session_seconds"] = item["duration_seconds"]
                # Sources can send a broad sleeping interval alongside detailed stages.
                # |asleep union awake| - |awake| removes every overlapping awake period.
                item["duration_seconds"] = (
                    union_seconds((s["start"], s["end"]) for s in asleep + awake)
                    - union_seconds((s["start"], s["end"]) for s in awake)
                    if asleep else (0 if samples and all(s["stage"] != "unknown" for s in samples) else None)
                )
                item["stages_seconds"] = {stage: union_seconds((s["start"], s["end"]) for s in samples if s["stage"] == stage) for stage in sorted({s["stage"] for s in samples})}
            result[key] = item
        return {"start_date": start_date, "end_date": end_date, "timezone": "Asia/Shanghai",
            "days": covered, "expected_days": (date.fromisoformat(end_date)-date.fromisoformat(start_date)).days+1, "metrics": result}

    @staticmethod
    def bill_filter(start_date=None, end_date=None, type=None, currency=None, category=None, book=None, account=None, account_from=None, account_to=None, status=None, query=None):
        clauses, args = [], []
        if start_date and end_date:
            start, end = date_window(start_date, end_date)
            clauses.extend(("occurred_at>=?", "occurred_at<?")); args.extend((start, end))
        elif start_date:
            start, _ = date_window(start_date, start_date)
            clauses.append("occurred_at>=?"); args.append(start)
        elif end_date:
            _, end = date_window(end_date, end_date)
            clauses.append("occurred_at<?"); args.append(end)
        if type is not None and type not in BILL_TYPES:
            raise ValueError("unknown bill type")
        if status is not None and status not in ("confirmed", "pending"):
            raise ValueError("unknown bill status")
        for key, value in (("type", type), ("currency", currency), ("category", category), ("book", book), ("account_from", account_from), ("account_to", account_to), ("status", status)):
            if value is not None:
                clauses.append(key+"=?"); args.append(value.upper() if key == "currency" else value)
        if account is not None:
            clauses.append("(account_from=? OR account_to=?)"); args.extend((account, account))
        if query:
            clauses.append("(instr(lower(coalesce(merchant,'')),lower(?))>0 OR instr(lower(coalesce(item,'')),lower(?))>0 OR instr(lower(coalesce(note,'')),lower(?))>0)"); args.extend((query, query, query))
        return " WHERE " + " AND ".join(clauses) if clauses else "", args

    def list_bills(self, offset=0, limit=50, **filters):
        pagination(offset, limit)
        where, args = self.bill_filter(**filters)
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM bills" + where + " ORDER BY occurred_at DESC,id LIMIT ? OFFSET ?", [*args, limit+1, offset]).fetchall()
        return {"records": [self.store.bill_row(row) for row in rows[:limit]], "next_offset": offset+limit if len(rows)>limit else None}

    def bill_summary(self, start_date: str, end_date: str, group_by: str | None = None, **filters):
        date_window(start_date, end_date)
        if group_by not in (None, "date", "month", "category", "book", "account_from", "account_to", "type", "currency"):
            raise ValueError("unknown bill grouping")
        where, args = self.bill_filter(start_date=start_date, end_date=end_date, **filters)
        pending = count = 0
        totals, groups = {}, {}
        def add(mapping, key, row):
            bucket = mapping.setdefault(key, {"count": 0, "amount": Decimal(0), "fee": Decimal(0)})
            bucket["count"] += 1
            for field in ("amount", "fee"):
                first, second = bucket[field], Decimal(row[field])
                with localcontext() as ctx:
                    ctx.prec = max(first.adjusted(), second.adjusted(), 0) - min(first.as_tuple().exponent, second.as_tuple().exponent, 0) + 2
                    bucket[field] = first + second
        with self.store.connection() as db:
            for row in db.execute("SELECT * FROM bills"+where, args):
                pending += row["status"] == "pending"
                if row["status"] == "pending" and filters.get("status") is None: continue
                count += 1
                key = (row["currency"], row["type"])
                add(totals, key, row)
                if group_by:
                    value = business_day(row["occurred_at"]) if group_by in ("date", "month") else row[group_by]
                    if group_by == "month": value = value[:7]
                    add(groups, (value, *key), row)
        def encode(mapping, grouped=False):
            values = []
            for key, value in sorted(mapping.items(), key=lambda item: tuple(str(x) for x in item[0])):
                values.append({**({group_by: key[0]} if grouped else {}), "currency": key[-2], "type": key[-1],
                    **{k: format(v, "f") if isinstance(v, Decimal) else v for k, v in value.items()}})
            return values
        return {"start_date": start_date, "end_date": end_date, "timezone": "Asia/Shanghai",
            "count": count, "pending_count": pending, "totals": encode(totals), "groups": encode(groups, True) if group_by else []}
