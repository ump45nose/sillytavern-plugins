"""每日推送的数据投影：按对象的聊天，以及仅属于业务日的健康和账单。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


from .contracts import canonical, instant, utcnow

TEXT_CHARS = 4000
PAGE_BYTES = 64 * 1024


class DailyPushData:
    def __init__(self, store, repository=None, records_client=None):
        self.store = store
        self.repository = repository
        self.records = records_client

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
        health = self._health(selected.isoformat())
        finance = self._finance(selected.isoformat())
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

    def _health(self, day):
        if self.records is None:
            raise ValueError("Personal Records API is not configured")
        result = self.records.health_summary(day, day)
        return {**result, "empty_day": result["days"] == 0}

    def _finance(self, day):
        result = self.records.bill_summary(day, day)
        bills = list(self.records.iter_bills(day, day))
        return {**result, "bills": bills, "total_bills": len(bills), "empty_day": not bills}


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
        result["finance"].update(deepcopy({k: v for k, v in snapshot["finance"].items() if k != "bills"}))
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
