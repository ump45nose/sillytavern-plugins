"""归档、HTTP 与 MCP 共用一个服务进程。"""

import hmac
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from personal_crm.archive import Archive
from personal_crm.archive.http import create_router, register_errors
from personal_crm.mcp import http_app

from .settings import Settings


def create_app(settings: Settings | None = None, repository=None) -> FastAPI:
    runtime = settings or Settings()
    archive = repository or Archive(
        runtime.database_url,
        runtime.crm_asset_root,
        gap_minutes=runtime.wechat_interaction_gap_minutes,
        create_schema=False,
    )
    mcp_application = http_app(archive, runtime)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp_application.lifespan(mcp_application):
            yield

    app = FastAPI(title="Personal CRM", version="0.3.0", lifespan=lifespan)
    app.state.repository = archive

    def authenticate(authorization, *, readonly=False):
        allowed = [runtime.crm_api_token]
        if readonly:
            allowed.append(runtime.crm_viewer_token)
        allowed = [token for token in allowed if token]
        if not allowed:
            raise HTTPException(503, "authentication_not_configured")
        if not any(
            hmac.compare_digest(authorization or "", "Bearer " + token) for token in allowed
        ):
            raise HTTPException(401, "unauthorized")

    register_errors(app)
    app.include_router(create_router(archive, authenticate, runtime.wechat_webhook_secret))

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "database": archive.integrity_check()}

    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    def oauth_protected_resource():
        if not runtime.oauth_enabled:
            raise HTTPException(404, "OAuth is not configured")
        base_url = runtime.public_base_url.rstrip("/")
        return JSONResponse(
            {
                "resource": f"{base_url}/mcp",
                "authorization_servers": [f"{base_url}/"],
                "scopes_supported": ["openid", "profile", "offline_access"],
                "bearer_methods_supported": ["header"],
            }
        )

    app.mount("/", mcp_application)
    return app


def main():
    import uvicorn

    settings = Settings()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
