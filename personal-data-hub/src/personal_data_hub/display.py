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
from .storage import active_sources, display_index as idx

DOMAINS = {'health_payloads': 'health', 'people': 'social', 'interactions': 'social', 'facts': 'social',
           'computer_summary': 'activity', 'recording': 'recordings', 'bill': 'finance', 'traffic_hourly': 'network',
           'recording_transcript': 'recordings', 'recording_daily_report': 'reports',
           'recording_summary': 'reports', 'recording_processing_status': 'recordings'}
MODULES = {'health', 'social', 'activity', 'recordings', 'reports', 'finance', 'network'}

def clean(v, size=160):
    return str(v or "").replace("\x00", "")[:size]

from .metric_rules import when, number, health_samples, health_value, finance_totals, sum_field

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
    elif kind in ("people", "interactions", "facts"):
        d = {k: clean(raw.get(k), 300) for k in ("id", "person_id", "display_name", "relationship_to_me", "channel", "direction", "status", "last_interaction_at")}
        if kind == "interactions": p["title"] = "交流记录"
    elif kind == "health_payloads":
        payload = n.get("payload", raw.get("payload_json", {}))
        d = {key: [sample for _, sample in values] for key, values in
             health_samples(payload, ('steps','sleep','resting_heart_rate','heart_rate','active_calories')).items()}
        p = {"title": "健康同步", "preview": "步数、睡眠与心率记录"}
    elif kind == "bill":
        bill = raw.get("bill", raw.get("payload", raw))
        d = {k: clean(bill.get(k), 200) for k in ("type", "state", "currency", "cateName", "shopName")}
        d["amount"] = clean(bill.get("money", n.get("amount")))
        p = {"title": clean(bill.get("shopName") or bill.get("cateName") or "账单"), "preview": clean(bill.get("remark"), 500)}
    elif kind == "traffic_hourly":
        d = {k: number(n.get(k)) or 0 for k in ("upload_bytes", "download_bytes")}
        d.update({k: clean(n.get(k, raw.get(k))) for k in ("device_id", "collector_id", "measurement_scope", "measurement_point", "host", "process", "category", "exit_node", "rule")})
        p = {"title": clean(raw.get("host") or "未知域名"), "preview": clean(raw.get("process") or "未知应用") + " · " + clean(raw.get("exit_node") or "未知路由")}
    elif kind == "recording":
        d = {"duration_ms": number(n.get("duration_ms")), "date": clean(n.get("date")), "download_state": clean(n.get("download_state")),
             "transcription_status": n.get("transcription_status"), "summary_status": n.get("summary_status")}
        p = {"title": "Plaud 录音 · " + d["date"], "preview": clean(n.get("summary") or n.get("transcript"), 500) or f"{int((d['duration_ms'] or 0) / 60000)} 分钟"}
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
            return [dict(r) for r in c.execute(select(idx).where(idx.c.domain.in_(domains), idx.c.source.in_(active_sources()))).mappings()]

    def overview(self, day, tz="Asia/Shanghai", modules="health,social", _rows=None):
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
            if module == "health":
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
                    value = health_value(key, [sample for sample, _ in chosen])
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
                    totals = finance_totals([r['data'] for r in current if (r['data'].get('currency') or '未知币种') == currency])[0]
                    pending = totals['pending_count']
                    refs = [r["record_id"] for r in current if (r["data"].get("currency") or "未知币种") == currency]
                    for k, label in [("expense", "支出"), ("income", "收入"), ("transfer", "转账")]: metric(k+":"+currency, label, str(totals[k]), currency, refs=refs)
                    metric("pending:"+currency, "待确认", pending, "笔", refs=refs)
                items = [card(r) for r in sorted(current, key=lambda r: when(r["occurred_at"]), reverse=True)[:8]]
            elif module == 'network':
                selected_rows = current
                default_source = 'shellcrash' if any(r['source'] == 'shellcrash' for r in selected_rows) else next((r['source'] for r in selected_rows), None)
                selected_rows = [r for r in selected_rows if r['source'] == default_source]
                for key, label in [('upload_bytes', '代理上传'), ('download_bytes', '代理下载')]:
                    metric(key, label, sum_field([r['data'] for r in selected_rows], key), 'bytes', refs=[r['record_id'] for r in selected_rows])
            else:
                metric("count", "今日记录", len(current) if any(r["occurred_at"] for r in group) else None, "条", refs=[r["record_id"] for r in current])
                readable = current or [r for r in group if r["occurred_at"] is None]
                items = [card(r) for r in sorted(readable, key=lambda r: when(r["occurred_at"]) or when(r["observed_at"]), reverse=True)[:5]]
            latest = max((when(r["observed_at"]) for r in group), default=None)
            result["modules"].append({"id": module, "metrics": metrics, "items": items, "updated_at": latest})
        return result

    def network(self, day, tz="Asia/Shanghai", source=""):
        start, end, _ = self.window(day, tz)
        with self.store.engine.connect() as c:
            known = list(c.execute(select(idx.c.source).where(idx.c.domain == "network").distinct()).scalars())
            selected = source or ("shellcrash" if "shellcrash" in known else next(iter(sorted(known)), ""))
            if source and source not in known: raise ValueError("unknown_network_source")
            rows = list(c.execute(select(idx).where(idx.c.domain == "network", idx.c.source == selected, idx.c.occurred_at >= start, idx.c.occurred_at < end)).mappings())
        totals = {key: sum_field([r["data"] for r in rows], key) for key in ("upload_bytes", "download_bytes")}
        dimensions = {}
        for key in ("process", "host", "exit_node", "category"):
            groups = {}
            for row in rows:
                name = row["data"].get(key) or "unknown"
                item = groups.setdefault(name, {"name": name, "upload_bytes": 0, "download_bytes": 0})
                for field in totals: item[field] += number(row["data"].get(field)) or 0
            dimensions[key] = sorted(groups.values(), key=lambda v: -(v["upload_bytes"] + v["download_bytes"]))[:20]
        return {"date": day, "source": selected, "sources": sorted(known), "scope": "proxy", "totals": totals, "dimensions": dimensions,
                "updated_at": max((r["observed_at"] for r in rows), key=when, default=None),
                "coverage_note": "经过所选代理采集入口的流量；每秒采样可能遗漏短连接。不同采集入口分别统计。"}

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

    def timeline(self, domains="social,activity,recordings,reports", cursor=None, limit=30, query="", start=None, end=None, person=None, kind=None):
        selected = domains.split(",")
        if not set(selected) <= MODULES | {"technical"} or not 1 <= limit <= 100 or len(query) > 200: raise ValueError("invalid_timeline")
        conditions = [idx.c.domain.in_(selected), idx.c.source.in_(active_sources())]
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
