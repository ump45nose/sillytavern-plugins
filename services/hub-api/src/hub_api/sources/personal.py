import asyncio
import json
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from .base import Adapter


def local_time(value, zone):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(zone).isoformat() if value else None


class Personal:
    def __init__(self, client, settings, now):
        self.client, self.settings, self.now = client, settings, now
        self.slots = asyncio.Semaphore(4)

    async def request(self, source, path, params=None, method="GET", body=None, write=False):
        token = getattr(self.settings, source + ("_write_token" if write and source == "crm" else "_token"))
        if not token:
            raise ValueError("source credential not configured")
        async with self.slots:
            response = await self.client.request(method, getattr(self.settings, source + "_url").rstrip("/") + path,
                headers={"Authorization": "Bearer " + token.get_secret_value()}, params=params, json=body)
        response.raise_for_status()
        return response.json()

    async def pages(self, path, **params):
        cursor = None
        seen = set()
        while True:
            page = await self.request("crm", "/api/v1/crm/" + path, {**params, "limit": 100, **({"cursor": cursor} if cursor else {})})
            yield page["items"]
            cursor = page.get("next_cursor")
            if not cursor:
                return
            if cursor in seen:
                raise ValueError("source cursor did not advance")
            seen.add(cursor)

    async def crm(self):
        today = self.now().date()
        start = today - timedelta(days=41)
        people = {}
        async for items in self.pages("people"):
            for p in items:
                people[p["id"]] = {k: p.get(k) for k in ("id", "name", "relationship", "last_interaction_date")}
        interactions, active_people, recent = 0, set(), []
        async for items in self.pages("interactions", start=start.isoformat(), end=today.isoformat()):
            for item in items:
                interactions += 1
                active_people.update(item["person_ids"])
                if item["date"] == today.isoformat():
                    recent.append({k: item.get(k) for k in ("id", "person_ids", "channel", "date", "started_at", "ended_at", "preview", "attachment_count")})
        # Source lists deliberately omit attachment IDs. Resolve only today's linked items.
        async def attachments(item):
            if not item.get("attachment_count"):
                return
            detail = await self.request("crm", "/api/v1/crm/interactions/" + quote(item["id"], safe=""))
            assets = await asyncio.gather(*(self.request("crm", "/api/v1/crm/attachments/" + quote(a, safe="")) for a in detail["attachment_ids"]))
            item["recordings"] = [{"id": "crm:" + a["id"], "title": a["name"], "duration_seconds": None}
                                  for a in assets if a.get("available") and a.get("media_type", "").startswith("audio/")]
        # Bound the outer fan-out too; the source request semaphore bounds I/O.
        for offset in range(0, len(recent), 4):
            await asyncio.gather(*(attachments(i) for i in recent[offset:offset + 4]))
        return {"people": people, "recent": recent, "cycle": {"start": start.isoformat(), "days": 42, "people": len(active_people), "interactions": interactions}}

    async def plaud(self):
        today = self.now().date()
        start = today - timedelta(days=41)
        page = await self.request("plaud", "/api/v1/archives", {"start_date": start.isoformat(), "end_date": today.isoformat(), "limit": 200})
        # At most 42 archive days are possible in this date window.
        days = page["items"]
        recordings = []
        if any(d["date"] == today.isoformat() for d in days):
            detail = await self.request("plaud", "/api/v1/archives/" + today.isoformat())
            recordings = [{"id": "plaud:" + today.isoformat() + ":" + a["id"], "title": a["name"],
                "start_at": local_time(a.get("start_at"), self.now().tzinfo),
                "duration_seconds": a["duration_ms"] / 1000 if a.get("duration_ms") is not None else None} for a in detail["audio"]]
        return {"recordings": recordings, "cycle_recordings": sum(d["audio_count"] for d in days)}

    async def memos(self):
        user = (await self.request("memos", "/api/v1/auth/me"))["user"]["name"]
        memos, stats = await asyncio.gather(
            self.request("memos", "/api/v1/memos", {"page_size": 20, "state": "NORMAL", "order_by": "create_time desc", "filter": "creator == " + json.dumps(user)}),
            self.request("memos", "/api/v1/" + user + ":getStats"))
        return {"recent": [{"id": m["name"].split("/")[-1], "created_at": local_time(m.get("createTime"), self.now().tzinfo),
                "content": m.get("content"), "tags": m.get("tags"), "visibility": m.get("visibility"),
                "url": self.settings.memos_public_url.rstrip("/") + "/m/" + m["name"].split("/")[-1]} for m in memos.get("memos", [])[:20]],
                "tags": [{"name": name, "count": count} for name, count in sorted(stats.get("tagCount", {}).items(), key=lambda p: (-p[1], p[0]))]}

    def adapters(self):
        return [Adapter(name, title, 60, getattr(self, name) if getattr(self.settings, name + "_token") else None)
                for name, title in [("crm", "Personal CRM"), ("plaud", "Plaud Archive"), ("memos", "Memos")]]
