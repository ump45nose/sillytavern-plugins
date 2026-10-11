from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .contracts import canonical, instant


def register_tools(server, store, auth, *, chat_reports=None):
    from .daily_push import DailyPushData, daily_push_page
    daily_data = DailyPushData(store)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_daily_push_data(day: str | None = None, timezone: str = "Asia/Taipei",
                            report_id: str | None = None, offset: int = 0, limit: int = 50) -> dict:
        """读取用于每日分析的数据：CRM 聊天按对象分组（时间、方向、正文），健康不回退历史值，财务只含当天汇总及账单。默认今天；事件传 report_id 读取冻结快照。next_offset 非空需续页；超长聊天按 message_id/text_offset 拼接。不生成原文附件。"""
        if report_id is not None:
            if chat_reports is None:
                raise ValueError("daily event reports are not configured")
            if day is not None:
                raise ValueError("report_id fixes the business day and timezone")
            return chat_reports.read_daily_push(report_id,
                subject=chat_reports.events.authenticated_subject(), offset=offset, limit=limit)
        return daily_push_page(daily_data.snapshot(day, timezone), offset, limit)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def read_data_asset(record_id: str, asset_id: str, offset_bytes: int = 0, limit_bytes: int = 65536) -> dict:
        """通过现有 MCP 授权分页读取附件原始字节；返回 base64 与完整文件 SHA-256。"""
        import base64
        if offset_bytes < 0 or not 1 <= limit_bytes <= 262144: raise ValueError("invalid_asset_page")
        row = store.get_record(record_id)
        a = next((a for a in (row or {}).get("assets", []) if a["id"] == asset_id), None)
        path = store.asset_path(asset_id) if a else None
        if path is None: raise ValueError("asset_not_found")
        with path.open("rb") as stream:
            stream.seek(offset_bytes); value = stream.read(limit_bytes)
        end = offset_bytes + len(value)
        return {**a, "offset_bytes": offset_bytes, "base64": base64.b64encode(value).decode(), "next_offset": end if end < a["size"] else None}

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def list_data_sources() -> list[dict]:
        """查看统一采集来源、数据量、最近采集结果及删除同步能力。"""
        return store.status()

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def list_data_records(source: str | None = None, kind: str | None = None, offset: int = 0, limit: int = 100, start: str | None = None, end: str | None = None, include_content: bool = False) -> dict:
        """分页列出归档 ID、来源、类型、时间、标题（最多160字符）及摘要（最多500字符）。默认不含 raw、normalized 和附件；正文请用 get_data_record，或显式设置 include_content=true 读取完整记录。"""
        begin, finish = instant(start), instant(end)
        if begin and finish and begin >= finish: raise ValueError("invalid_time_range")
        return store.record_page(source, kind, offset, limit, begin, finish, include_content)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_data_record(record_id: str) -> dict | None:
        """读取一条完整的采集记录和原始载荷，不执行源端写入。"""
        return store.get_record(record_id)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_recording_content(record_id: str) -> dict | None:
        """读取录音文字稿、分源转录、每日摘要和关联日报；明确区分草稿、完整稿与处理失败。"""
        return store.recording_content(record_id)

    @server.tool(auth=auth, annotations={"readOnlyHint": True})
    def get_data_asset_info(record_id: str, asset_id: str) -> dict:
        """查看记录的附件摘要；文件下载端点需要独立的采集 API Bearer 鉴权。"""
        row = store.get_record(record_id)
        if row is None: raise ValueError("record_not_found")
        a = next((a for a in row["assets"] if a["id"] == asset_id), None)
        if a is None: raise ValueError("asset_not_found")
        return {**a, "path": "/api/v1/assets/" + asset_id, "requires": "hub_api_bearer"}


class ArchiveDailyReviews:
    """原 CRM 日报查询工具从聚合存储读取，保持分页和正文续读契约。"""
    def __init__(self, store): self.store = store

    def snapshot(self, source, day=None, timezone="Asia/Shanghai", summary_type="preferred"):
        from personal_crm.daily_review import business_date, DailyReviewService
        selected, zone = business_date(day, timezone)
        start = datetime.combine(selected, time.min, zone)
        rows = []
        offset = 0
        kind = "computer_summary" if source == "codex_skylight" else "memo"
        while True:
            page = self.store.list_records(kind=kind, offset=offset, limit=1000, start=start if kind == "computer_summary" else None, end=start + timedelta(days=1) if kind == "computer_summary" else None)
            rows.extend(page)
            if len(page) < 1000: break
            offset += len(page)
        result = []
        for row in rows:
            normal = row["normalized"]
            if kind == "memo":
                if normal.get("state") != "NORMAL" or not normal.get("content", "").strip() or normal["content"].lstrip().splitlines()[0].strip() not in {f"#日报 {selected}", f"# 日报 {selected}"}: continue
            elif summary_type in ("6h", "10min") and normal.get("interval") != summary_type: continue
            result.append({"id": row["id"], "source": source, "content": normal.get("content", ""), "source_ref": normal.get("source_ref"), "started_at": row["occurred_at"].isoformat() if row["occurred_at"] else None, "summary_type": normal.get("interval"), "title": normal.get("content", "").splitlines()[0] if normal.get("content") else ""})
        if summary_type == "preferred" and kind == "computer_summary":
            # 使用原有 6h 覆盖 / 10min 补齐算法。
            chosen = [r for r in result if r["summary_type"] == "6h"]
            spans = [(instant(r["started_at"]), instant(r["started_at"]) + timedelta(hours=6)) for r in chosen if r["started_at"]]
            result = chosen + [r for r in result if r["summary_type"] == "10min" and not any(a <= instant(r["started_at"]) < b for a, b in spans)]
        return {"metadata": {"source": source, "date": selected.isoformat(), "timezone": timezone, "total_count": len(result), "empty_day": not result, "summary_type": summary_type}, "records": result}

    def query(self, source, day=None, timezone="Asia/Shanghai", offset=0, limit=20, summary_type="preferred"):
        from personal_crm.daily_review import report_page
        report = self.snapshot(source, day, timezone, summary_type)
        return report_page(report["metadata"], report["records"], offset, limit)

    def read_content(self, source, record_id, day=None, timezone="Asia/Shanghai", offset=0, limit=12000):
        from personal_crm.daily_review import content_page
        report = self.snapshot(source, day, timezone, "all")
        return {**report["metadata"], **content_page(report["records"], record_id, offset, limit)}
