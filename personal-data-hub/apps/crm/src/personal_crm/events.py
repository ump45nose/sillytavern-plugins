"""按用户隔离的每日完整聊天报告与可重试事件生产者。"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from personal_crm.core.domain import ensure_utc, utcnow

EVENT_NAME = "crm.daily_chat.ready"
CONTENT_PREFIX = "消息内容："
PAGE_BYTES = 64 * 1024


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(value) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


class ChatEventProducer:
    """定时产出不可变全文快照；发布失败保留同一报告与事件编号。"""

    def __init__(
        self,
        repository,
        events,
        *,
        owner: str,
        storage_path: str,
        timezone: str = "Asia/Taipei",
        send_time: str = "23:00",
        poll_seconds: int = 60,
        clock=utcnow,
        daily_data=None,
    ):
        if not owner or owner.strip() != owner:
            raise ValueError("chat event owner is required")
        if not re.fullmatch(r"\d{2}:\d{2}", send_time):
            raise ValueError("chat event time must be HH:MM")
        hour, minute = map(int, send_time.split(":"))
        self.send_time = time(hour, minute)
        self.zone = ZoneInfo(timezone)
        self.repo, self.events, self.owner = repository, events, owner
        self.daily_data = daily_data
        self.clock, self.poll_seconds = clock, max(10, poll_seconds)
        self.directory = Path(storage_path)
        if self.directory.is_symlink():
            raise ValueError("chat event storage must not be a symlink")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.reports = self.directory / "reports"
        if self.reports.is_symlink():
            raise ValueError("chat reports storage must not be a symlink")
        self.reports.mkdir(exist_ok=True, mode=0o700)
        self.reports.chmod(0o700)
        self._async_lock = asyncio.Lock()
        events.register_event(
            EVENT_NAME,
            ("每日分析数据已就绪：聊天按对象分组，健康和财务仅包含本业务日。"
             "使用事件 read_tool/read_arguments 分页读取并按对象展示；无需生成完整原文附件。"
             if daily_data is not None else
             "每日完整微信聊天记录已就绪；按页读取原文，包含此前未收录的晚到记录。"),
            {"type": "object", "properties": {}, "additionalProperties": False},
            {
                "type": "object",
                "properties": {
                    "report_id": {"type": "string"},
                    "business_day": {"type": "string"},
                    "timezone": {"type": "string"},
                    "window_start": {"type": "string"},
                    "window_end": {"type": "string"},
                    "generated_at": {"type": "string"},
                    "daily_count": {"type": "integer", "minimum": 0},
                    "supplemental_count": {"type": "integer", "minimum": 0},
                    "total_count": {"type": "integer", "minimum": 0},
                    "content_unavailable_count": {"type": "integer", "minimum": 0},
                    "empty_day": {"type": "boolean"},
                    "coverage": {"type": "object"},
                    "read_tool": {"type": "string"},
                    "read_arguments": {"type": "object"},
                },
                "required": [
                    "report_id",
                    "business_day",
                    "window_start",
                    "window_end",
                    "daily_count",
                    "supplemental_count",
                    "total_count",
                    "empty_day",
                    "read_tool",
                    "read_arguments",
                ],
                "additionalProperties": False,
            },
            subjects={owner},
        )

    @contextmanager
    def _locked(self):
        fd = os.open(self.directory / "producer.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    @staticmethod
    def _write(path: Path, value) -> None:
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(_json(value))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def _load_state(self):
        path = self.directory / "state.json"
        if not path.exists():
            return None
        value = json.loads(path.read_text())
        if value.get("owner") != self.owner or value.get("version") != 1:
            raise ValueError("chat event state identity or version mismatch")
        if value.get("timezone") != self.zone.key:
            raise ValueError("chat event timezone change requires explicit state migration")
        return value

    def _all_records(self, cutoff: datetime):
        """只读取源数据；没有原文的旧记录明确标为未采集，不用摘要替代。"""
        records = self.repo.report_records(cutoff)
        watermarks = [row['synced_through'] for row in self.repo.list_sync_clients()]
        return records, watermarks

    @staticmethod
    def _version(record) -> str:
        # 人物改名不重发整段历史；原文补齐会作为补充记录再次提供。
        return _digest({k: v for k, v in record.items() if k not in {"person_name", "sender"}})

    def _snapshot(self, now: datetime):
        """准备并持久化报告；有待发布报告时原样重用。"""
        with self._locked():
            state = self._load_state()
            today = now.astimezone(self.zone).date()
            if state is None:
                start = datetime.combine(today, time.min, self.zone)
                historical, _ = self._all_records(start)
                state = {
                    "version": 1,
                    "owner": self.owner,
                    "timezone": self.zone.key,
                    "started_at": now.isoformat(),
                    "next_day": today.isoformat(),
                    "seen": {r["id"]: self._version(r) for r in historical},
                    "pending_report": None,
                }
                self._write(self.directory / "state.json", state)
            if state["pending_report"]:
                return self._load_report(state["pending_report"])
            day = date.fromisoformat(state["next_day"])
            due = datetime.combine(day, self.send_time, self.zone)
            if now < due:
                return None
            start = datetime.combine(day, time.min, self.zone)
            # 当天覆盖实际产生报告的时刻；停机补发保持历史日期的原定截止时间。
            cutoff = now.astimezone(self.zone) if day == today else due
            rows, watermarks = self._all_records(cutoff)
            records, versions = [], {}
            for record in rows:
                occurred = datetime.fromisoformat(record["occurred_at"])
                version = self._version(record)
                current = occurred >= start
                if not current and state["seen"].get(record["id"]) == version:
                    continue
                record["section"] = "daily" if current else "supplement"
                record["business_day"] = occurred.astimezone(self.zone).date().isoformat()
                record["supplement_reason"] = (
                    None
                    if current
                    else "content_completed"
                    if record["id"] in state["seen"]
                    else "late_arrival_or_after_previous_cutoff"
                )
                records.append(record)
                versions[record["id"]] = version
            report_id = uuid5(
                NAMESPACE_URL, f"crm-daily-chat:{self.owner}:{self.zone.key}:{day.isoformat()}"
            ).hex
            watermark_values = [ensure_utc(value) for value in watermarks if value is not None]
            observed = min(watermark_values) if watermark_values else None
            gaps = []
            if observed is None or len(watermark_values) != len(watermarks) or observed < cutoff:
                all_clients_known = len(watermark_values) == len(watermarks)
                gap_start = (
                    max(start, observed) if observed is not None and all_clients_known else start
                )
                gaps.append(
                    {
                        "start": gap_start.isoformat(),
                        "end": cutoff.isoformat(),
                        "reason": "source_sync_not_confirmed",
                        "completion": "next_daily_supplement",
                    }
                )
            midnight = datetime.combine(day + timedelta(days=1), time.min, self.zone)
            if cutoff < midnight:
                gaps.append(
                    {
                        "start": cutoff.isoformat(),
                        "end": midnight.isoformat(),
                        "reason": "after_daily_cutoff",
                        "completion": "next_daily_supplement",
                    }
                )
            daily_count = sum(r["section"] == "daily" for r in records)
            metadata = {
                "report_id": report_id,
                "business_day": day.isoformat(),
                "timezone": self.zone.key,
                "window_start": start.isoformat(),
                "window_end": cutoff.isoformat(),
                "generated_at": now.isoformat(),
                "daily_count": daily_count,
                "supplemental_count": len(records) - daily_count,
                "total_count": len(records),
                "content_unavailable_count": sum(r["content"] is None for r in records),
                "empty_day": daily_count == 0,
                "coverage": {
                    "pending_windows": gaps,
                    "sync_client_count": len(watermarks),
                    "minimum_observed_sync_time": observed.isoformat() if observed else None,
                    "supplemental_days": sorted(
                        {r["business_day"] for r in records if r["section"] == "supplement"}
                    ),
                },
                "read_tool": "get_chat_event_report",
                "read_arguments": {"report_id": report_id, "offset": 0, "limit": 50},
            }
            report = {
                "owner": self.owner,
                "metadata": metadata,
                "records": records,
                "_consumed_versions": versions,
                "_next_day": (day + timedelta(days=1)).isoformat(),
            }
            if self.daily_data is not None:
                report["_daily_push"] = self.daily_data.snapshot(
                    day.isoformat(), self.zone.key, cutoff=cutoff, chats=records
                )
                metadata["read_tool"] = "get_daily_push_data"
                view = report["_daily_push"]
                metadata["empty_day"] = (not view["crm"]["total_messages"]
                    and view["health"]["empty_day"] and view["finance"]["empty_day"])
            self._write(self.reports / (report_id + ".json"), report)
            state["pending_report"] = report_id
            self._write(self.directory / "state.json", state)
            return report

    def _load_report(self, report_id: str):
        if not re.fullmatch(r"[a-f0-9]{32}", report_id):
            raise ValueError("invalid report id")
        path = self.reports / (report_id + ".json")
        if path.is_symlink():
            raise ValueError("invalid report storage")
        try:
            report = json.loads(path.read_text())
        except FileNotFoundError:
            raise ValueError("report not found") from None
        if report.get("owner") != self.owner:
            raise PermissionError("report access denied")
        return report

    def _commit(self, report):
        with self._locked():
            state = self._load_state()
            if state["pending_report"] != report["metadata"]["report_id"]:
                return
            state["seen"].update(report["_consumed_versions"])
            state["next_day"] = report["_next_day"]
            state["pending_report"] = None
            self._write(self.directory / "state.json", state)

    async def run_once(self, now: datetime | None = None):
        now = ensure_utc(now or self.clock())
        async with self._async_lock:
            report = await asyncio.to_thread(self._snapshot, now)
            if report is None:
                return None
            metadata = report["metadata"]
            result = await self.events.publish(
                EVENT_NAME,
                metadata,
                subject=self.owner,
                event_id="crm-daily-chat-" + metadata["report_id"],
                timestamp=metadata["generated_at"],
            )
            await asyncio.to_thread(self._commit, report)
            return {
                "report_id": metadata["report_id"],
                "total_count": metadata["total_count"],
                "delivery": result,
            }

    async def serve(self):
        while True:
            try:
                await self.run_once()
            except Exception as error:
                logging.getLogger(__name__).error(
                    "CRM daily chat event failed (%s)", type(error).__name__
                )
            await asyncio.sleep(self.poll_seconds)

    def _authorized_report(self, report_id: str, subject: str):
        if not isinstance(subject, str) or not hmac.compare_digest(
            subject.encode(), self.owner.encode()
        ):
            raise PermissionError("report access denied")
        return self._load_report(report_id)

    def read_page(self, report_id: str, *, subject: str, offset: int = 0, limit: int = 50):
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid page")
        report = self._authorized_report(report_id, subject)
        output, used = [], 0
        source = report["records"]
        for original in source[offset : offset + limit]:
            record = dict(original)
            content = record["content"]
            record["content_total_chars"] = len(content) if content is not None else 0
            record["next_content_offset"] = None
            if content is not None and len(content) > 4000:
                record["content"] = content[:4000]
                record["next_content_offset"] = 4000
                record["content_read_tool"] = "get_chat_event_message"
            size = len(_json(record).encode())
            if output and used + size > PAGE_BYTES:
                break
            output.append(record)
            used += size
        following = offset + len(output)
        return {
            **report["metadata"],
            "offset": offset,
            "records": output,
            "next_offset": following if following < len(source) else None,
        }

    def read_daily_push(self, report_id: str, *, subject: str, offset: int = 0, limit: int = 50):
        report = self._authorized_report(report_id, subject)
        if self.daily_data is None:
            raise ValueError("daily push data is not configured")
        from personal_data_hub.daily_push import daily_push_page

        snapshot = report.get("_daily_push")
        if snapshot is None:
            # 原报告保持不可变；升级前报告的投影视图仅在首次读取时冻结到单独文件。
            with self._locked():
                directory = self.directory / "daily-push"
                directory.mkdir(exist_ok=True, mode=0o700)
                path = directory / (report_id + ".json")
                if path.is_symlink():
                    raise ValueError("invalid report storage")
                if path.exists():
                    snapshot = json.loads(path.read_text())
                else:
                    metadata = report["metadata"]
                    snapshot = self.daily_data.snapshot(metadata["business_day"], self.zone.key,
                        cutoff=metadata["window_end"], chats=report["records"])
                    self._write(path, snapshot)
        return {"report_id": report_id, **daily_push_page(snapshot, offset, limit)}

    def read_message(
        self,
        report_id: str,
        record_id: str,
        *,
        subject: str,
        offset: int = 0,
        limit: int = 12000,
    ):
        if offset < 0 or not 1 <= limit <= 16000:
            raise ValueError("invalid content page")
        report = self._authorized_report(report_id, subject)
        record = next((r for r in report["records"] if r["id"] == record_id), None)
        if record is None:
            raise ValueError("record not found")
        content = record["content"]
        total = len(content) if content is not None else 0
        end = min(offset + limit, total)
        return {
            "report_id": report_id,
            "record_id": record_id,
            "person_name": record["person_name"],
            "occurred_at": record["occurred_at"],
            "direction": record["direction"],
            "content_status": record["content_status"],
            "content": content[offset:end] if content is not None else None,
            "offset": offset,
            "total_chars": total,
            "next_offset": end if end < total else None,
        }


def register_chat_event_tools(server, producer: ChatEventProducer, *, auth):
    """原 MCP 权限之外，再检查报告实际所有者。"""

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_chat_event_report(report_id: str, offset: int = 0, limit: int = 50):
        """分页读取每日完整聊天记录；next_content_offset 非空时继续读取单条原文。"""
        return producer.read_page(
            report_id, subject=producer.events.authenticated_subject(), offset=offset, limit=limit
        )

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_chat_event_message(
        report_id: str,
        record_id: str,
        offset: int = 0,
        limit: int = 12000,
    ):
        """读取报告内单条聊天原文的下一段；保留每个字符，不做摘要。"""
        return producer.read_message(
            report_id,
            record_id,
            subject=producer.events.authenticated_subject(),
            offset=offset,
            limit=limit,
        )
