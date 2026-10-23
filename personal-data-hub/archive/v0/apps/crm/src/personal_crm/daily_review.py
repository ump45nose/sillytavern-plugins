"""只读查询已同步的 Codex Skysight 摘要与 Hermes Memos 日报。"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from personal_crm.core.domain import utcnow

SOURCES = {"codex_skylight", "memos"}
PAGE_BYTES = 64 * 1024
SUMMARY_NAME = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})-.+-(6h|10min)-memory-summary\.md$"
)


def business_date(day: str | None, timezone: str, clock=utcnow) -> tuple[date, ZoneInfo]:
    zone = ZoneInfo(timezone)
    if day is None:
        return clock().astimezone(zone).date(), zone
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("day must be YYYY-MM-DD")
    return date.fromisoformat(day), zone


def report_page(metadata: dict, records: list[dict], offset: int, limit: int) -> dict:
    """分页展示正文首段；为每条长正文返回稳定的续读参数。"""

    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError("invalid page")
    output, used = [], 0
    for original in records[offset : offset + limit]:
        record = dict(original)
        content = record["content"]
        record["content"] = content[:4000]
        record["content_total_chars"] = len(content)
        record["next_content_offset"] = 4000 if len(content) > 4000 else None
        if record["next_content_offset"] is not None:
            snapshot = metadata.get("report_id")
            record["content_read_tool"] = (
                "get_daily_review_event_content" if snapshot else "get_daily_review_content"
            )
            record["content_read_arguments"] = {
                "source": metadata["source"],
                "record_id": record["id"],
                "offset": 4000,
                **({"report_id": snapshot} if snapshot else {"day": metadata["date"]}),
            }
            if not snapshot:
                record["content_read_arguments"]["timezone"] = metadata["timezone"]
        size = len(json.dumps(record, ensure_ascii=False).encode())
        if output and used + size > PAGE_BYTES:
            break
        output.append(record)
        used += size
    following = offset + len(output)
    return {
        **metadata,
        "offset": offset,
        "records": output,
        "next_offset": following if following < len(records) else None,
    }


def content_page(records: list[dict], record_id: str, offset: int, limit: int) -> dict:
    if offset < 0 or not 1 <= limit <= 16000:
        raise ValueError("invalid content page")
    record = next((record for record in records if record["id"] == record_id), None)
    if record is None:
        raise ValueError("record not found")
    content = record["content"]
    end = min(offset + limit, len(content))
    return {
        "record_id": record_id,
        "content": content[offset:end],
        "offset": offset,
        "total_chars": len(content),
        "next_offset": end if end < len(content) else None,
    }


class DailyReviewService:
    def __init__(
        self,
        *,
        skylight_path: str,
        memos_database_path: str,
        memos_creator_id: int = 1,
        clock=utcnow,
    ):
        if memos_creator_id < 1:
            raise ValueError("memos creator id must be positive")
        self.skylight_path = skylight_path
        self.memos_database_path = memos_database_path
        self.memos_creator_id = memos_creator_id
        self.clock = clock

    def _skylight(self, day: date, zone: ZoneInfo, summary_type: str) -> list[dict]:
        if summary_type not in {"preferred", "all", "6h", "10min"}:
            raise ValueError("summary_type must be preferred, all, 6h or 10min")
        if not self.skylight_path or not Path(self.skylight_path).is_dir():
            raise ValueError("Codex Skylight source is not configured or unavailable")
        start = datetime.combine(day, time.min, zone)
        end = start + timedelta(days=1)
        candidates = []
        for path in sorted(Path(self.skylight_path).glob("*-memory-summary.md")):
            match = SUMMARY_NAME.fullmatch(path.name)
            if not match or path.is_symlink() or not path.is_file():
                continue
            occurred = datetime.strptime(match[1], "%Y-%m-%dT%H-%M-%S").replace(tzinfo=UTC)
            if start <= occurred < end:
                candidates.append((path, occurred, match[2]))
        six_hours = [occurred for _, occurred, kind in candidates if kind == "6h"]
        records = []
        for path, occurred, kind in candidates:
            if summary_type in {"6h", "10min"} and kind != summary_type:
                continue
            if (
                summary_type == "preferred"
                and kind == "10min"
                and any(begin <= occurred < begin + timedelta(hours=6) for begin in six_hours)
            ):
                continue
            records.append(
                {
                    "id": path.name,
                    "summary_type": kind,
                    "occurred_at": occurred.astimezone(zone).isoformat(),
                    "window_end": (occurred + timedelta(minutes=360 if kind == "6h" else 10))
                    .astimezone(zone)
                    .isoformat(),
                    "content": path.read_text(encoding="utf-8"),
                }
            )
        return records

    def _memos(self, day: date) -> list[dict]:
        if not self.memos_database_path or not Path(self.memos_database_path).is_file():
            raise ValueError("Memos daily report source is not configured or unavailable")
        # 整个源目录需只读挂载，保留 WAL/SHM 的可见性；不得使用 immutable 忽略 WAL。
        uri = Path(self.memos_database_path).absolute().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            connection.execute("PRAGMA query_only=ON")
            rows = connection.execute(
                "SELECT uid, created_ts, updated_ts, content FROM memo "
                "WHERE creator_id=? AND row_status='NORMAL' "
                "AND (content LIKE ? OR content LIKE ?) ORDER BY created_ts, id",
                (
                    self.memos_creator_id,
                    f"%#日报 {day.isoformat()}%",
                    f"%# 日报 {day.isoformat()}%",
                ),
            ).fetchall()
        records = []
        for uid, created, updated, content in rows:
            heading = content.lstrip().splitlines()[0] if content.strip() else ""
            # 业务日期取日报标题，不把次日补写的日报误归到创建日。
            if heading.strip() not in {f"#日报 {day}", f"# 日报 {day}"}:
                continue
            records.append(
                {
                    "id": f"memos/{uid}",
                    "created_at": datetime.fromtimestamp(created, UTC).isoformat(),
                    "updated_at": datetime.fromtimestamp(updated, UTC).isoformat(),
                    "content": content,
                }
            )
        return records

    def snapshot(
        self,
        source: str,
        day: str | None = None,
        timezone: str = "Asia/Shanghai",
        summary_type: str = "preferred",
    ) -> dict:
        if source not in SOURCES:
            raise ValueError("unknown daily review source")
        selected, zone = business_date(day, timezone, self.clock)
        records = (
            self._skylight(selected, zone, summary_type)
            if source == "codex_skylight"
            else self._memos(selected)
        )
        return {
            "metadata": {
                "source": source,
                "date": selected.isoformat(),
                "timezone": zone.key,
                "total_count": len(records),
                "empty_day": not records,
                **({"summary_type": summary_type} if source == "codex_skylight" else {}),
            },
            "records": records,
        }

    def query(
        self,
        source: str,
        day: str | None = None,
        timezone: str = "Asia/Shanghai",
        offset: int = 0,
        limit: int = 20,
        summary_type: str = "preferred",
    ) -> dict:
        report = self.snapshot(source, day, timezone, summary_type)
        return report_page(report["metadata"], report["records"], offset, limit)

    def read_content(
        self,
        source: str,
        record_id: str,
        day: str | None = None,
        timezone: str = "Asia/Shanghai",
        offset: int = 0,
        limit: int = 12000,
    ):
        report = self.snapshot(source, day, timezone, summary_type="all")
        return {
            **report["metadata"],
            **content_page(report["records"], record_id, offset, limit),
        }


def register_daily_review_tools(server, service: DailyReviewService, *, auth):
    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_daily_codex_skylight(
        day: str | None = None,
        timezone: str = "Asia/Shanghai",
        offset: int = 0,
        limit: int = 20,
        summary_type: str = "preferred",
    ) -> dict:
        """查询同步的 Codex Skylight（源目录名 Skysight）正文，默认今天。

        按摘要文件 UTC 开始时间转换到指定时区筛选；preferred 优先 6h，10min 补空档。
        all 返回全部文件。长正文通过 content_read_arguments 续读，不做二次摘要。
        """
        return service.query("codex_skylight", day, timezone, offset, limit, summary_type)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_daily_memos_report(
        day: str | None = None, timezone: str = "Asia/Shanghai", offset: int = 0, limit: int = 20
    ) -> dict:
        """查询 Hermes 日报流程写入 Memos 的 #日报 YYYY-MM-DD 正文，默认今天。

        按标题业务日期读取指定作者的正常日报，保留全文；empty_day 表示当天尚无日报。
        """
        return service.query("memos", day, timezone, offset, limit)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_daily_review_content(
        source: str,
        record_id: str,
        day: str | None = None,
        timezone: str = "Asia/Shanghai",
        offset: int = 0,
        limit: int = 12000,
    ) -> dict:
        """续读查询结果的完整正文；source 为 codex_skylight 或 memos。

        使用查询返回的明确 day；源正文可能更新。事件快照请使用事件正文读取工具。
        """
        return service.read_content(source, record_id, day, timezone, offset, limit)
