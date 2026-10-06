"""Deterministic, bounded display models. Never returns raw collection payloads."""
from __future__ import annotations

import base64
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import and_, or_, select
from .storage import display_index as idx

DOMAINS = {"calendar_event": "agenda", "google_task": "agenda", "health_payloads": "health",
           "people": "social", "interactions": "social", "facts": "social", "computer_summary": "activity",
           "recording": "recordings", "hermes_execution_report": "reports", "email": "mail", "git_commit": "git",
           "memo": "notes", "memory": "notes", "bill": "finance", "token_day": "usage", "traffic_hourly": "network"}
MODULES = {"agenda", "health", "social", "activity", "recordings", "reports", "mail", "git", "notes", "finance", "usage", "network"}

def clean(v, size=160):
    return str(v or "").replace("\x00", "")[:size]

def when(v):
    if isinstance(v, datetime): return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        x = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return x if x.tzinfo else x.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError): return None

def number(v):
    try:
        x = float(v)
        return x if not isinstance(v, bool) and math.isfinite(x) else None
    except (ValueError, TypeError): return None

def index_value(kind, external_id, raw, n):
    from .storage import Store
    p = Store.preview_fields(kind, external_id, raw, n)
    d = {}
    if kind == "computer_summary":
        content = n.get("content", "")
        def front(key):
            m = re.search(r"^" + key + r":\s*(.+)$", content[:5000], re.M)
            return clean(m.group(1).strip('"\''), 500) if m else None
        p["title"] = (front("title") or "电脑活动摘要")[:160]
        p["preview"] = front("description") or clean(content, 500)
        d = {"interval": n.get("interval")}
    elif kind == "google_task":
        tl = raw.get("tasklist", {})
        d = {k: clean(raw.get(k), 200) for k in ("status", "due", "completed", "parent", "position", "webViewLink")}
        d.update(external_id=clean(raw.get("id")), list_id=clean(n.get("tasklist_id")), list_title=clean(tl.get("title")))
    elif kind == "calendar_event":
        d = {"start": raw.get("start", {}), "end": raw.get("end", {}), "calendar": clean(n.get("calendar")), "status": clean(raw.get("status")), "link": clean(raw.get("htmlLink"), 1000)}
    elif kind in ("people", "interactions", "facts"):
        d = {k: clean(raw.get(k), 300) for k in ("id", "person_id", "display_name", "relationship_to_me", "channel", "direction", "status", "last_interaction_at")}
        if kind == "interactions": p["title"] = "交流记录"
    elif kind == "health_payloads":
        payload = n.get("payload", raw.get("payload_json", {}))
        if isinstance(payload, str):
            try: payload = json.loads(payload)
            except ValueError: payload = {}
        for metric, field, keys in [("steps", "count", ("end_time", "start_time")), ("sleep", "duration_seconds", ("session_end_time",)), ("resting_heart_rate", "bpm", ("time",)), ("heart_rate", "bpm", ("time",)), ("active_calories", "calories", ("end_time", "start_time"))]:
            samples = []
            source_samples = payload.get(metric, []) if isinstance(payload, dict) else []
            if not isinstance(source_samples, list):
                # Older exports may use scalar metrics. Only use an explicit source timestamp.
                source_samples = [{field: source_samples, keys[0]: payload.get("timestamp")}] if number(source_samples) is not None else []
            for s in source_samples:
                if not isinstance(s, dict): continue
                value = number(s.get(field)); t = next((when(s.get(k)) for k in keys if when(s.get(k))), None)
                if value is None or t is None: continue
                meta = s.get("metadata") if isinstance(s.get("metadata"), dict) else {}
                sample = {"time": t.isoformat(), "value": value, "origin": clean(meta.get("data_origin")), "device": clean(meta.get("device"))}
                if metric in ("steps", "active_calories") and when(s.get("start_time")) and when(s["start_time"]) <= t:
                    sample["day_time"] = when(s["start_time"]).isoformat()
                samples.append(sample)
            d[metric] = samples
        p = {"title": "健康同步", "preview": "步数、睡眠与心率记录"}
    elif kind == "bill":
        bill = raw.get("bill", raw.get("payload", raw))
        d = {k: clean(bill.get(k), 200) for k in ("type", "state", "currency", "cateName", "shopName")}
        d["amount"] = clean(bill.get("money", n.get("amount")))
        p = {"title": clean(bill.get("shopName") or bill.get("cateName") or "账单"), "preview": clean(bill.get("remark"), 500)}
    elif kind == "token_day":
        d = {k: n.get(k) for k in ("tokens", "estimated_cost_usd", "device", "date", "source_timezone")}
        p = {"title": "AI 用量 · " + clean(n.get("device")), "preview": clean(n.get("date"))}
    elif kind == "traffic_hourly":
        d = {k: number(n.get(k)) or 0 for k in ("upload_bytes", "download_bytes")}
    elif kind == "recording":
        d = {"duration_ms": number(n.get("duration_ms")), "date": clean(n.get("date")), "download_state": clean(n.get("download_state"))}
        p = {"title": "Plaud 录音", "preview": f"{int((d['duration_ms'] or 0) / 60000)} 分钟"}
    elif kind in ("hermes_execution_report", "memo", "memory"):
        content = n.get("content", raw.get("content", ""))
        heading = re.search(r"^#\s+(.+)$", content[:5000], re.M) if isinstance(content, str) else None
        p["title"] = clean(heading.group(1) if heading else p["title"])
    return dict(domain=DOMAINS.get(kind, "technical"), title=p["title"][:160], preview=p["preview"][:500], data=d)

def card(row, people=None):
    d = row["data"]
    name = (people or {}).get(d.get("person_id"), {}).get("title")
    return {"id": row["record_id"], "source": row["source"], "kind": row["kind"], "domain": row["domain"],
            "occurred_at": row["occurred_at"], "observed_at": row["observed_at"], "title": name or row["title"], "preview": row["preview"],
            "subtitle": name or d.get("channel") or d.get("list_title") or "", "metadata": {k: v for k, v in d.items() if not isinstance(v, list)}}

class Display:
    def __init__(self, store): self.store = store

    def window(self, day, tz):
        zone = ZoneInfo(tz)
        start = datetime.combine(date.fromisoformat(day), datetime.min.time(), zone)
        return start, start + timedelta(days=1), zone

    def rows(self, domains):
        with self.store.engine.connect() as c:
            return [dict(r) for r in c.execute(select(idx).where(idx.c.domain.in_(domains))).mappings()]

    def overview(self, day, tz="Asia/Shanghai", modules="agenda,health,social", _rows=None):
        start, end, zone = self.window(day, tz)
        selected = modules.split(",")
        if not set(selected) <= MODULES: raise ValueError("invalid_modules")
        rows = self.rows(selected) if _rows is None else _rows
        people = {r["data"].get("id"): r for r in rows if r["kind"] == "people"}
        result = {"date": day, "timezone": tz, "modules": []}
        for module in selected:
            group = [r for r in rows if r["domain"] == module]
            current = [r for r in group if r["occurred_at"] and start <= when(r["occurred_at"]) < end]
            metrics = []
            def metric(key, label, value, unit, data_date=day, refs=None):
                references = set(refs or [])
                updated = max((r["observed_at"] for r in group if r["record_id"] in references), key=when, default=None)
                metrics.append({"id": key, "label": label, "value": value, "unit": unit, "date": data_date, "updated_at": updated, "record_ids": list(dict.fromkeys(refs or []))[:10]})
            items = []
            if module == "agenda":
                events = []
                for r in group:
                    if r["kind"] != "calendar_event": continue
                    d = r["data"]; a = d.get("start", {}); b = d.get("end", {})
                    s = when(a.get("dateTime")) if a.get("dateTime") else (datetime.combine(date.fromisoformat(a["date"]), datetime.min.time(), zone) if a.get("date") else None)
                    e = when(b.get("dateTime")) if b.get("dateTime") else (datetime.combine(date.fromisoformat(b["date"]), datetime.min.time(), zone) if b.get("date") else None)
                    if s and e and s < end and e > start: events.append(r)
                tasks = [r for r in group if r["kind"] == "google_task" and r["data"].get("status") != "completed"]
                tasks.sort(key=lambda r: (r["data"].get("due") or "9999", r["title"]))
                metric("tasks", "待办任务", len(tasks), "项", refs=[r["record_id"] for r in tasks])
                metric("events", "今日日程", len(events), "项", refs=[r["record_id"] for r in events])
                items = [card(r) for r in sorted(events, key=lambda r: when(r["occurred_at"]) or start)[:10] + tasks[:12]]
            elif module == "health":
                for key, label, unit, factor in [("steps", "步数", "步", 1), ("sleep", "睡眠", "小时", 1/3600), ("resting_heart_rate", "静息心率", "次/分", 1), ("active_calories", "活动热量", "千卡", 1)]:
                    samples = {}
                    for r in sorted(group, key=lambda r: when(r["observed_at"])):
                        for s in r["data"].get(key, []):
                            t = when(s["time"])
                            if t and (t < end or (key in ("steps", "active_calories") and t == end)): samples[(s["time"], s["origin"], s["device"])] = (s, r["record_id"])
                    def sample_date(s): return (when(s.get("day_time")) or when(s["time"])).astimezone(zone).date().isoformat()
                    chosen = [(s, rid) for s, rid in samples.values() if sample_date(s) == day]
                    sample_day = day
                    if not chosen and samples:
                        sample_day = max(sample_date(s) for s, _ in samples.values() if sample_date(s) <= day)
                        chosen = [(s, rid) for s, rid in samples.values() if sample_date(s) == sample_day]
                    # Daily cumulative snapshots use their valid maximum. Sleep is a set of sessions.
                    value = None
                    if chosen:
                        if key == "sleep":
                            intervals = sorted((when(s["time"]) - timedelta(seconds=s["value"]), when(s["time"])) for s, _ in chosen if 0 < s["value"] <= 86400)
                            merged = []
                            for a, b in intervals:
                                if merged and a <= merged[-1][1]: merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                                else: merged.append((a, b))
                            value = sum((b-a).total_seconds() for a, b in merged) if merged else None
                        else:
                            value = max(s["value"] for s, _ in chosen) if key in ("steps", "active_calories") else max(chosen, key=lambda x: when(x[0]["time"]))[0]["value"]
                        if value is not None: value = round(value * factor, 2)
                    metric(key, label, value, unit, sample_day, [rid for _, rid in chosen])
            elif module == "social":
                interactions = sorted([r for r in group if r["kind"] == "interactions" and (not r["occurred_at"] or when(r["occurred_at"]) < end)], key=lambda r: when(r["occurred_at"]) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
                contacts_today = [r for r in current if r["kind"] == "interactions"]
                metric("interactions", "今日交流", len(contacts_today), "条", refs=[r["record_id"] for r in contacts_today])
                metric("people", "交流人数", len({r["data"].get("person_id") for r in contacts_today if r["data"].get("person_id")}), "人", refs=[r["record_id"] for r in contacts_today])
                seen = set()
                for r in interactions:
                    pid = r["data"].get("person_id")
                    if pid in seen: continue
                    seen.add(pid); value = card(r, people)
                    value["metadata"]["person_record_id"] = people[pid]["record_id"] if pid in people else ""
                    items.append(value)
                    if len(items) == 5: break
            elif module == "finance":
                for currency in sorted({r["data"].get("currency") or "未知币种" for r in current}):
                    totals = {"expense": Decimal(0), "income": Decimal(0), "transfer": Decimal(0)}
                    pending = 0
                    for r in current:
                        d = r["data"]
                        if (d.get("currency") or "未知币种") != currency: continue
                        if d.get("state") == "Wait2Edit": pending += 1; continue
                        try: amount = Decimal(d.get("amount", ""))
                        except InvalidOperation: continue
                        if not amount.is_finite(): continue
                        typ = d.get("type", "")
                        bucket = "transfer" if typ == "Transfer" else "expense" if typ.startswith("Expend") else "income"
                        totals[bucket] += amount
                    refs = [r["record_id"] for r in current if (r["data"].get("currency") or "未知币种") == currency]
                    for k, label in [("expense", "支出"), ("income", "收入"), ("transfer", "转账")]: metric(k+":"+currency, label, str(totals[k]), currency, refs=refs)
                    metric("pending:"+currency, "待确认", pending, "笔", refs=refs)
                items = [card(r) for r in sorted(current, key=lambda r: when(r["occurred_at"]), reverse=True)[:8]]
            elif module in ("usage", "network"):
                selected_rows = [r for r in group if r["data"].get("date") == day] if module == "usage" else current
                fields = [("tokens", "Token", "tokens"), ("estimated_cost_usd", "估算费用", "USD")] if module == "usage" else [("upload_bytes", "上传", "bytes"), ("download_bytes", "下载", "bytes")]
                for key, label, unit in fields: metric(key, label, sum(number(r["data"].get(key)) or 0 for r in selected_rows) if selected_rows else None, unit, refs=[r["record_id"] for r in selected_rows])
                items = [card(r) for r in selected_rows[:5]] if module == "usage" else []
            else:
                metric("count", "今日记录", len(current) if any(r["occurred_at"] for r in group) else None, "条", refs=[r["record_id"] for r in current])
                readable = current or [r for r in group if r["occurred_at"] is None]
                items = [card(r) for r in sorted(readable, key=lambda r: when(r["occurred_at"]) or when(r["observed_at"]), reverse=True)[:5]]
            latest = max((when(r["observed_at"]) for r in group), default=None)
            result["modules"].append({"id": module, "metrics": metrics, "items": items, "updated_at": latest})
        return result

    def trends(self, day, tz, modules, days=7):
        if days not in (7, 30): raise ValueError("invalid_days")
        start, _, _ = self.window(day, tz)
        if not set(modules.split(",")) <= MODULES: raise ValueError("invalid_modules")
        rows = self.rows(modules.split(","))
        values = []
        for i in reversed(range(days)):
            value = self.overview((start.date()-timedelta(days=i)).isoformat(), tz, modules, rows)
            for module in value["modules"]:
                module["items"] = []
                for metric in module["metrics"]:
                    metric["record_ids"] = []
                    if metric["date"] != value["date"]: metric["value"] = None
            values.append(value)
        return {"days": values}

    def timeline(self, domains="social,activity,recordings,reports,mail,git,notes", cursor=None, limit=30, query="", start=None, end=None, person=None, kind=None):
        selected = domains.split(",")
        if not set(selected) <= MODULES | {"technical"} or not 1 <= limit <= 100 or len(query) > 200: raise ValueError("invalid_timeline")
        conditions = [idx.c.domain.in_(selected)]
        if kind: conditions.append(idx.c.kind == kind)
        if query: conditions.append((idx.c.title + " " + idx.c.preview).icontains(query, autoescape=True))
        if start: conditions.append(idx.c.occurred_at >= start)
        if end: conditions.append(idx.c.occurred_at < end)
        if cursor:
            try:
                payload = json.loads(base64.urlsafe_b64decode(cursor))
                t = when(payload[0]); rid = payload[1]
                if not isinstance(rid, str) or len(rid) != 64 or (payload[0] is not None and t is None): raise ValueError()
                conditions.append(or_(idx.c.occurred_at < t, and_(idx.c.occurred_at == t, idx.c.record_id > rid), idx.c.occurred_at.is_(None)) if t else and_(idx.c.occurred_at.is_(None), idx.c.record_id > rid))
            except Exception: raise ValueError("invalid_cursor") from None
        with self.store.engine.connect() as c:
            people = {r["data"].get("id"): dict(r) for r in c.execute(select(idx).where(idx.c.kind == "people")).mappings()}
            if person:
                # JSON extraction is safe here: this index never contains AX NUL.
                conditions.append(idx.c.data["person_id"].as_string() == person)
            rows = list(c.execute(select(idx).where(*conditions).order_by(idx.c.occurred_at.desc().nulls_last(), idx.c.record_id).limit(limit+1)).mappings())
        more = len(rows) > limit; rows = rows[:limit]
        next_cursor = None
        if more:
            last = rows[-1]; t = when(last["occurred_at"])
            next_cursor = base64.urlsafe_b64encode(json.dumps([t.isoformat() if t else None, last["record_id"]]).encode()).decode()
        return {"items": [card(r, people) for r in rows], "next_cursor": next_cursor}
