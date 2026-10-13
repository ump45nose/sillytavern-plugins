"""修正固定FastMCP版本的CIMD Token地址，保留完整客户端签名校验。"""

from fastmcp.server.auth.auth import PrivateKeyJWTClientAuthenticator, TokenHandler
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp.server.auth.routes import cors_middleware
from starlette.routing import Route


class PlatformOIDCProxy(OIDCProxy):
    """兼容3.4.4根域名AnyHttpUrl自动补斜线造成的private_key_jwt受众错误。"""

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """仅替换Token处理器，令受众与OAuth discovery发布的地址完全一致。"""
        routes = super().get_routes(mcp_path)
        if self._cimd_manager is None:
            return routes
        # 不能接受多个受众或跳过JWT检查；精确采用已发布的单斜线Token端点。
        authenticator = PrivateKeyJWTClientAuthenticator(
            provider=self,
            cimd_manager=self._cimd_manager,
            token_endpoint_url=str(self.base_url).rstrip("/") + "/token",
        )
        handler = TokenHandler(provider=self, client_authenticator=authenticator)
        return [
            Route(
                "/token",
                endpoint=cors_middleware(handler.handle, ["POST", "OPTIONS"]),
                methods=["POST", "OPTIONS"],
            )
            if route.path == "/token"
            else route
            for route in routes
        ]
