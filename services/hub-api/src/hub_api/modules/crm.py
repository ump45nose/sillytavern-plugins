from datetime import date, datetime, timedelta
from ..sources.personal import local_time


def assemble(crm, plaud, now, stale_days=30, cycle_start=None):
    if crm is None and plaud is None:
        return None
    recordings = plaud["recordings"] if plaud else []
    recent = [] if crm else None
    for item in crm["recent"] if crm else []:
        recording = (item.get("recordings") or [None])[0]
        if not recording and item.get("started_at"):
            start = datetime.fromisoformat(item["started_at"].replace("Z", "+00:00"))
            stop = datetime.fromisoformat(item["ended_at"].replace("Z", "+00:00")) if item.get("ended_at") else start
            candidates = []
            for r in recordings:
                if r["start_at"] is None or r["duration_seconds"] is None:
                    continue
                a = datetime.fromisoformat(r["start_at"])
                b = a + timedelta(seconds=r["duration_seconds"])
                if a.astimezone(now.tzinfo).date() != start.astimezone(now.tzinfo).date():
                    continue
                overlap = (min(stop, b) - max(start, a)).total_seconds()
                if overlap > 0 or (start == stop and a <= start < b):
                    candidates.append((overlap, -abs((start-a).total_seconds()), r["id"], r))
            if candidates:
                recording = {k: max(candidates, key=lambda x: x[:3])[3][k] for k in ("id", "title", "duration_seconds")}
        for pid in item["person_ids"]:
            p = crm["people"].get(pid, {})
            recent.append({"id": item["id"] + ":" + pid, "person_id": pid, "name": p.get("name"), "relation": p.get("relationship"),
                "channel": {"wechat": "微信", "meeting": "会议", "phone": "电话", "face_to_face": "面谈"}.get(item["channel"], item["channel"]),
                "time": local_time(item["started_at"], now.tzinfo), "summary": item.get("preview"), "recording": recording})
    stale = None
    if crm:
        stale = []
        for pid, person in crm["people"].items():
            if person["last_interaction_date"]:
                days = (now.date() - date.fromisoformat(person["last_interaction_date"])).days
                if days > stale_days:
                    stale.append({"person_id": pid, "name": person["name"], "days": days})
        stale.sort(key=lambda p: (-p["days"], p["person_id"]))
        stale = stale[:5]
    return {"today": recent, "cycle": {"start": cycle_start or (now.date() - timedelta(days=41)).isoformat(), "days": 42,
            "people": crm["cycle"]["people"] if crm else None, "interactions": crm["cycle"]["interactions"] if crm else None,
            "recordings": plaud["cycle_recordings"] if plaud else None}, "stale": stale}
