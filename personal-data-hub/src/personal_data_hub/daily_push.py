"""每日推送的数据投影：按对象的聊天，以及仅属于业务日的健康和账单。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .contracts import canonical, instant, utcnow
from .display import Display, when
from .metric_rules import bill_kind, finance_totals, health_value
from .storage import display_index, records

TEXT_CHARS = 4000
PAGE_BYTES = 64 * 1024


class DailyPushData:
    def __init__(self, store, repository=None):
        self.store = store
        self.repository = repository

    def snapshot(self, day=None, timezone="Asia/Taipei", *, cutoff=None, chats=None):
        zone = ZoneInfo(timezone)
        selected = date.fromisoformat(day) if day else utcnow().astimezone(zone).date()
        start = datetime.combine(selected, time.min, zone)
        end = start + timedelta(days=1)
        finish = min(instant(cutoff), end) if cutoff else (
            min(utcnow(), end) if selected == utcnow().astimezone(zone).date() else end)
        if finish < start:
            raise ValueError("invalid_daily_cutoff")
        if chats is None:
            chats = self._chats(start, finish, zone)
        contacts = {}
        for row in sorted(chats, key=lambda r: (r["person_id"], r["occurred_at"], r["id"])):
            contact = contacts.setdefault(row["person_id"], {
                "person_id": row["person_id"], "name": row["person_name"], "messages": [],
            })
            message = {"time": row["occurred_at"], "direction": row["direction"],
                       "text": row["content"], "_id": row["id"]}
            if row.get("sender"):
                message["sender"] = row["sender"]
            if row.get("section") == "supplement":
                message["late_arrival"] = True
            if row["content"] is None:
                message["content_status"] = "not_collected"
            if row.get("ended_at"):
                message["ended_at"] = row["ended_at"]
            contact["messages"].append(message)
        health = self._health(selected.isoformat(), timezone, start, finish)
        finance = self._finance(start, finish, zone)
        return {"date": selected.isoformat(), "timezone": timezone,
                "cutoff": finish.astimezone(zone).isoformat(),
                "crm": {"contacts": list(contacts.values()), "total_contacts": len(contacts),
                        "total_messages": sum(len(c["messages"]) for c in contacts.values())},
                "health": health, "finance": finance}

    def _chats(self, start, end, zone):
        if self.repository is None:
            from personal_crm.archive import Archive
            self.repository = Archive(engine=self.store.engine, asset_root=self.store.root, create_schema=False)
        return self.repository.report_records(instant(end), instant(start))

    def _health(self, day, timezone, start, finish):
        # 按样本业务日期筛选；接收时间不代表样本属于今天，且不能回退到昨日值。
        zone = ZoneInfo(timezone)
        with self.store.engine.connect() as connection:
            rows = [dict(row) for row in connection.execute(select(display_index)
                    .where(display_index.c.kind == "health_payloads")).mappings()]
        selected = []
        for row in rows:
            data = {}
            for key, samples in row["data"].items():
                data[key] = [s for s in samples if
                    (when(s.get("day_time")) or when(s["time"])).astimezone(zone).date().isoformat() == day
                    and when(s["time"]) <= finish]
            if any(data.values()):
                selected.append({**row, "data": data})
        overview = Display(self.store).overview(day, timezone, "health", _rows=selected)
        metrics = []
        missing = []
        for metric in overview["modules"][0]["metrics"]:
            if metric["value"] is None:
                missing.append(metric["id"])
                continue
            samples = [s for row in selected for s in row["data"].get(metric["id"], [])]
            metrics.append({"metric": metric["id"], "label": metric["label"],
                            "value": metric["value"], "unit": metric["unit"],
                            "measured_at": max(when(s["time"]) for s in samples).astimezone(zone).isoformat()})
        heart = {(s["time"], s["origin"], s["device"]): s
                 for row in selected for s in row["data"].get("heart_rate", [])}
        if heart:
            values = [s["value"] for s in heart.values()]
            metrics.append({"metric": "heart_rate", "label": "心率", "unit": "次/分",
                            "min": min(values), "max": max(values),
                            "average": health_value('heart_rate', list(heart.values())), "sample_count": len(values),
                            "measured_at": max(when(s["time"]) for s in heart.values()).astimezone(zone).isoformat()})
        else:
            missing.append("heart_rate")
        return {"metrics": metrics, "missing_metrics": missing, "empty_day": not metrics}

    def _finance(self, start, finish, zone):
        with self.store.engine.connect() as connection:
            rows = connection.execute(select(records.c.raw, records.c.normalized, records.c.occurred_at)
                    .where(records.c.kind == "bill", records.c.occurred_at >= instant(start),
                           records.c.occurred_at < instant(finish))
                    .order_by(records.c.occurred_at, records.c.id)).mappings().all()
        bills, amounts = [], []
        for row in rows:
            raw = row["raw"]
            bill = raw.get("bill", raw.get("payload", raw))
            normal = row["normalized"]
            currency = bill.get("currency") or normal.get("currency") or "未知币种"
            amount = str(bill.get("money", bill.get("amount", normal.get("amount", ""))))
            typ, state = str(bill.get("type", "")), str(bill.get("state", ""))
            kind = bill_kind(typ)
            amounts.append(dict(currency=currency, amount=amount, type=typ, state=state))
            bills.append({"time": instant(row["occurred_at"]).astimezone(zone).isoformat(),
                          "type": kind, "amount": amount, "currency": currency,
                          "category": bill.get("cateName", ""), "merchant": bill.get("shopName", ""),
                          "note": bill.get("remark", ""), "state": state})
        return {"totals": finance_totals(amounts),
                "bills": bills, "total_bills": len(bills), "empty_day": not bills}


def daily_push_page(snapshot, offset=0, limit=50):
    """按对象连续分页；超长正文分段，下一页不会丢失任何字符。"""
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("invalid_daily_page")
    units = []
    for contact in snapshot["crm"]["contacts"]:
        for original in contact["messages"]:
            message = {k: v for k, v in original.items() if k != "_id"}
            text = original["text"]
            if text is not None and len(text) > TEXT_CHARS:
                for position in range(0, len(text), TEXT_CHARS):
                    units.append(("chat", contact, {**message, "text": text[position:position + TEXT_CHARS],
                        "message_id": original["_id"], "text_offset": position, "text_total_chars": len(text)}))
            else:
                units.append(("chat", contact, message))
    units.extend(("bill", None, bill) for bill in snapshot["finance"]["bills"])
    result = {k: snapshot[k] for k in ("date", "timezone", "cutoff")}
    result["crm"] = {"contacts": [], "total_contacts": snapshot["crm"]["total_contacts"],
                     "total_messages": snapshot["crm"]["total_messages"]}
    result["finance"] = {"bills": [], "total_bills": snapshot["finance"]["total_bills"]}
    if offset == 0:
        result["health"] = deepcopy(snapshot["health"])
        result["finance"].update(totals=deepcopy(snapshot["finance"]["totals"]),
                                 empty_day=snapshot["finance"]["empty_day"])
    groups, used, count = {}, len(canonical(result).encode()), 0
    for kind, contact, value in units[offset:offset + limit]:
        size = len(canonical(value).encode())
        if count and used + size > PAGE_BYTES:
            break
        if kind == "chat":
            pid = contact["person_id"]
            if pid not in groups:
                groups[pid] = {"person_id": pid, "name": contact["name"],
                               "total_messages": len(contact["messages"]), "messages": []}
                result["crm"]["contacts"].append(groups[pid])
            groups[pid]["messages"].append(dict(value))
        else:
            result["finance"]["bills"].append(dict(value))
        used += size
        count += 1
    following = offset + count
    result.update(offset=offset, next_offset=following if following < len(units) else None)
    return result
