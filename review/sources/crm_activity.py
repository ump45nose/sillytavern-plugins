"""直接读取独立 CRM，不保存聊天镜像或日报输入快照。"""
from __future__ import annotations

from datetime import datetime, time, timedelta
import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from review.domain import Evidence, EvidenceKind, TimeWindow
from review.evidence import stable_evidence_id
from review.sources.base import SourceResult
from review.sources.cursor import encode_cursor


class CrmActivitySource:
    def __init__(self, base_url: str, token_file: str | Path) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = Path(token_file).read_text().strip()
        if not self.token:
            raise ValueError("CRM read token is empty")
        self.http = build_opener(ProxyHandler({}))

    def _pages(self, resource, **filters):
        cursor, seen = None, set()
        while True:
            query = urlencode({**filters, "limit": 100, **({"cursor": cursor} if cursor else {})})
            request = Request(f"{self.base_url}/api/v1/crm/{resource}?{query}",
                              headers={"Authorization": f"Bearer {self.token}"})
            with self.http.open(request, timeout=30) as response:
                page = json.load(response)
            yield from page["items"]
            cursor = page["next_cursor"]
            if not cursor:
                return
            if cursor in seen:
                raise ValueError("CRM returned a repeated pagination cursor")
            seen.add(cursor)

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        del checkpoint
        day = window.start.date().isoformat()
        rows = []
        for row in self._pages("interactions", start=day,
                               end=(window.end - timedelta(microseconds=1)).date().isoformat()):
            start = (datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                     if row.get("started_at") else
                     datetime.combine(datetime.fromisoformat(row["date"]).date(), time.min, window.start.tzinfo))
            end = datetime.fromisoformat(row["ended_at"].replace("Z", "+00:00")) if row.get("ended_at") else start
            if start < window.end and end >= window.start:
                rows.append(row)
        ids = {person for row in rows for person in row["person_ids"]}
        names = {row["id"]: row["name"] for row in self._pages("people")} if ids else {}
        people = sorted({names.get(pid, "未命名联系人") for pid in ids})
        fact = (f"互动 {len(rows)} 次 / {len(ids)} 人（{'、'.join(people)}）"
                if rows else "今日 CRM 无互动")
        fingerprint = hashlib.sha256(json.dumps(
            sorted((row["id"], row["updated_at"]) for row in rows), separators=(",", ":")
        ).encode()).hexdigest()
        evidence = Evidence(
            stable_evidence_id("crm", day, fingerprint), "crm", EvidenceKind.RELATIONSHIP,
            min(datetime.now(window.start.tzinfo), window.end - timedelta(microseconds=1)), fact,
            source_ref=f"crm-api:{day}@{fingerprint}",
            payload={"change_count": len(rows), "people": people},
        )
        return SourceResult("crm", [evidence], next_checkpoint=encode_cursor([evidence]))
