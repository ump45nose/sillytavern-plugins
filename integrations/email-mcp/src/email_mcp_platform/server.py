"""同进程挂载原邮件 SDK，不启动第二个 HTTP 后端。"""

import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import version

import uvicorn
from fastmcp.server import create_proxy
from fastmcp.server.middleware.authorization import AuthMiddleware

from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server

from .events import EmailEventProducer, EventSettings, register_email_event


def email_permission(config):
    """未知或未明确标记只读的工具按写权限处理。"""

    def check(context):
        annotations = getattr(context.component, "annotations", None)
        readonly = annotations is not None and annotations.readOnlyHint is True
        permission = "read" if readonly else "write"
        auth = authorize(permission, config)
        return auth is None or auth(context)

    return check


def create_app(config=None):
    from mcp_email_server.app import mcp as upstream
    from mcp_email_server.runtime import get_application_runtime

    # 与上游 CLI 相同的启动预检；选中的 managed 库不可用时拒绝启动。
    get_application_runtime().management.legacy_compatibility.validate_runtime()
    config = config or RuntimeConfig.from_env("email-mcp")
    # 原业务已有查询/结果限制；不再叠加可能改变邮件写入行为的超时。
    config = config.model_copy(
        update={
            "version": version("mcp-email-server"),
            "requests_per_minute": 0,
            "tool_timeout_seconds": 0,
            "max_output_bytes": 0,
        }
    )
    settings = EventSettings.from_env(config)
    events = producer = None
    event_lifetime = None
    if settings.enabled:
        from mcp_platform.events import EventService

        from .event_provider import UpstreamHeaderProvider

        events = EventService(config, storage_path=settings.state_path / "deliveries")
        register_email_event(events, settings.owner)
        producer = EmailEventProducer(
            settings, config.authorized_usernames, UpstreamHeaderProvider(), events
        )

        @asynccontextmanager
        async def event_lifetime(_server):
            async with asyncio.TaskGroup() as group:
                tasks = [
                    group.create_task(events.serve()),
                    group.create_task(producer.serve()),
                ]
                try:
                    yield
                finally:
                    for task in tasks:
                        task.cancel()

    server = create_server(
        config,
        lifespan=event_lifetime,
        healthcheck=lambda: {
            "status": "ok",
            "database": "ok",
            "email_server": version("mcp-email-server"),
            "email_events_enabled": events is not None,
            "email_header_failures": producer.store.header_failure_count() if producer else 0,
        },
    )
    server.mount(create_proxy(upstream))
    if not config.development_no_auth:
        server.add_middleware(AuthMiddleware(auth=email_permission(config)))
    app = (create_http_app(server, config, events=events)
           if events is not None else create_http_app(server, config))
    app.state.email_events = events
    app.state.email_event_producer = producer
    return app, server, config


def main():
    app, _, config = create_app()
    uvicorn.run(app, host=config.host, port=config.port)
