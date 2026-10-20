"""直接读取独立 CRM，不保存聊天镜像或日报输入快照。"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

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

    def _get(self, resource: str):
        request = Request(f"{self.base_url}/api/v1/crm/{resource}",
                          headers={"Authorization": f"Bearer {self.token}"})
        with self.http.open(request, timeout=30) as response:
            return json.load(response)

    def _pages(self, resource, **filters):
        cursor, seen = None, set()
        while True:
            query = urlencode({**filters, "limit": 100, **({"cursor": cursor} if cursor else {})})
            page = self._get(f"{resource}?{query}")
            yield from page["items"]
            cursor = page["next_cursor"]
            if not cursor:
                return
            if cursor in seen:
                raise ValueError("CRM returned a repeated pagination cursor")
            seen.add(cursor)

    def _interactions(self, window: TimeWindow):
        rows = []
        for row in self._pages("interactions", start=window.start.date().isoformat(),
                               end=(window.end - timedelta(microseconds=1)).date().isoformat()):
            start = (datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                     if row.get("started_at") else
                     datetime.combine(datetime.fromisoformat(row["date"]).date(), time.min, window.start.tzinfo))
            end = datetime.fromisoformat(row["ended_at"].replace("Z", "+00:00")) if row.get("ended_at") else start
            if start < window.end and end >= window.start:
                rows.append(row)
        return rows

    def _people(self, rows):
        return {row["id"]: row["name"] for row in self._pages("people")} if rows else {}

    @staticmethod
    def _window_content(row, window: TimeWindow) -> str:
        """按 CRM 的北京时间消息格式裁切跨日/跨截止点正文，保留多行消息。"""
        content = row["content"]
        if row.get("source") != "wechat" or not content.strip():
            return content.strip()
        day = date.fromisoformat(row["date"])
        lines, keep, found = [], False, False
        for line in content.splitlines(keepends=True):
            match = re.match(r"^(?:(\d{4}-\d{2}-\d{2}) )?(\d{2}:\d{2}) .+?[：:]", line)
            if match:
                found = True
                if match[1]:
                    day = date.fromisoformat(match[1])
                stamp = datetime.combine(day, time.fromisoformat(match[2]), ZoneInfo("Asia/Shanghai"))
                keep = window.start <= stamp < window.end
            if keep:
                lines.append(line)
        if not found:
            raise ValueError("CRM 微信正文缺少消息时间，无法确定日报窗口")
        return "".join(lines).strip()

    def read_conversations(self, window: TimeWindow) -> dict:
        """只读当日正文交给日报 Agent；不写入复盘状态或聊天镜像。"""
        rows = self._interactions(window)
        names = self._people(rows)
        conversations = []
        for row in rows:
            detail = self._get("interactions/" + quote(row["id"], safe=""))
            content = self._window_content(detail, window)
            if content:
                conversations.append({
                    "people": [names[pid] for pid in detail["person_ids"]],
                    "content": content,
                })
        return {"date": window.start.date().isoformat(),
                "window": {"start": window.start.isoformat(), "end": window.end.isoformat()},
                "conversations": conversations}

    def collect(self, window: TimeWindow, checkpoint: str | None) -> SourceResult:
        del checkpoint
        day = window.start.date().isoformat()
        rows = self._interactions(window)
        ids = {person for row in rows for person in row["person_ids"]}
        names = self._people(rows)
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
