from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server
from mcp_platform.events import EventService
from fastmcp.exceptions import ToolError

from . import __version__
from .config import Settings
from .daily_events import DailyUsageProducer
from .http_read import attach_read_routes
from .reports import ReportStore, build_report, report_page, summary


READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


def build_application(settings=None, runtime_config=None, extra_producers=None):
    settings = settings or Settings.from_env()
    config = runtime_config or RuntimeConfig.from_env("usage-monitor-mcp")
    config.version = __version__
    if settings.events_enabled and settings.event_subject not in config.authorized_usernames:
        raise ValueError("用量事件主体必须属于 OIDC_AUTHORIZED_USERNAMES")
    events = EventService(config, storage_path=str(settings.data_dir / "events"))
    daily = DailyUsageProducer(events, settings)
    daily.register()
    producers = [daily] if settings.events_enabled else []
    producers.extend(extra_producers or [])
    dingtalk = None
    if os.getenv("DINGTALK_EVENTS_ENABLED", "false").lower() == "true":
        from dingtalk_events import build_producer
        config_path = os.environ["DINGTALK_EVENTS_CONFIG"]
        dingtalk = build_producer(events, config_path=config_path,
                                 storage_path=str(settings.data_dir / "dingtalk-events"))
        if dingtalk.subject not in config.authorized_usernames:
            raise ValueError("钉钉事件主体必须属于 OIDC_AUTHORIZED_USERNAMES")
        dingtalk.register()
        producers.append(dingtalk)

    @asynccontextmanager
    async def lifespan(_server):
        tasks = [asyncio.create_task(events.serve())]
        tasks.extend(asyncio.create_task(p.serve()) for p in producers)
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    server = create_server(config, instructions=(
        "读取 Token Monitor 与 ShellCrash 日报。日期默认 Asia/Taipei；当日范围为 00:00 到生成时。"
        "估算成本不等于实付，缺失额度不等于 0。模型、工具、设备分别是同一用量的不同维度，不能重复相加。"
        "usage.daily_ready 提供已存档报告 ID，get_usage_report 可分页取明细。"
        "钉钉事件与只读事件记录如已配置也由此服务提供，业务操作仍使用原钉钉 MCP。"),
        lifespan=lifespan, healthcheck=lambda: {"status": "ok", "ok": True, "service": "usage-monitor-mcp"})
    store = ReportStore(settings.data_dir)
    permission = authorize("read", config)

    def principal():
        if config.development_no_auth:
            return settings.event_subject or "local"
        return events.authenticated_subject()

    def usage_owner():
        subject = principal()
        if settings.event_subject and subject != settings.event_subject:
            raise ToolError("forbidden: 此数据源属于其他主体")

    @server.tool(annotations=READ_ONLY, auth=permission)
    async def get_daily_usage(date: str | None = None) -> dict:
        """读取指定日期当前可得的用量，date 为 YYYY-MM-DD；默认今天，带完整性和时区说明。"""
        usage_owner()
        try:
            report = await asyncio.to_thread(build_report, settings, date)
            result = summary(report)
            result["mode"] = "current_query"
            result["archived_report_id"] = report["report_id"] if store.get(report["report_id"]) else None
            result["report_id"] = None
            result["note"] = "此结果为当前查询，已存档日报保留当晚生成时的数据；其明细请按 archived_report_id 查询。"
            return result
        except ValueError as error:
            raise ToolError(str(error)) from None

    @server.tool(annotations=READ_ONLY, auth=permission)
    def list_usage_reports(offset: int = 0, limit: int = 30) -> dict:
        """按日期倒序列出已保存日报及可继续查询的报告 ID。"""
        usage_owner()
        try:
            return store.list(offset, limit)
        except ValueError as error:
            raise ToolError(str(error)) from None

    @server.tool(annotations=READ_ONLY, auth=permission)
    def get_usage_report(report_id: str, section: str = "summary", offset: int = 0, limit: int = 50) -> dict:
        """按报告 ID 分页读取摘要、模型、工具、设备、额度或流量明细；summary 会列出可用 section。"""
        usage_owner()
        try:
            report = store.get(report_id)
            if report is None:
                raise ToolError("report_not_found")
            return report_page(report, section, offset, limit)
        except ValueError as error:
            raise ToolError(str(error)) from None

    @server.tool(annotations=READ_ONLY, auth=permission)
    def get_usage_event_status() -> dict:
        """读取用量日报时间与最近入队记录；入队成功不代表客户端已显示通知。"""
        usage_owner()
        return daily.status()

    if dingtalk is not None:
        @server.tool(annotations=READ_ONLY, auth=permission)
        def get_dingtalk_event_status() -> dict:
            """读取钉钉事件采集状态、已启用来源和受阻原因。"""
            try:
                return dingtalk.status(subject=principal())
            except PermissionError:
                raise ToolError("forbidden") from None

        @server.tool(annotations=READ_ONLY, auth=permission)
        def list_dingtalk_events(limit: int = 20) -> dict:
            """列出此主体最近的钉钉事件摘要。"""
            try:
                return dingtalk.list_recent(subject=principal(), limit=limit)
            except PermissionError:
                raise ToolError("forbidden") from None

        @server.tool(annotations=READ_ONLY, auth=permission)
        def get_dingtalk_event(event_id: str) -> dict:
            """按事件 ID 读取钉钉事件详情；仅此数据源所属主体可读。"""
            try:
                return dingtalk.detail(event_id, subject=principal())
            except PermissionError:
                raise ToolError("forbidden") from None

    attach_read_routes(server, settings)
    return create_http_app(server, config, events=events)


def main():
    import uvicorn
    settings = Settings.from_env()
    config = RuntimeConfig.from_env("usage-monitor-mcp")
    uvicorn.run(build_application(settings, config), host=config.host, port=config.port, access_log=False)
