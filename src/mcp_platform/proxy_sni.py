"""修复httpcore 1.0.9的HTTP代理隧道忽略已验证SNI扩展的问题。"""

import ipaddress
import ssl
from importlib.metadata import version

import certifi
from httpcore._async.http_proxy import AsyncTunnelHTTPConnection

_installed = False


def install_proxy_sni_compatibility() -> None:
    """只修正带Host/SNI扩展的固定IP请求，保留DNS固定与TLS证书校验。"""
    global _installed
    if _installed:
        return
    if version("httpcore") != "1.0.9":
        raise RuntimeError("代理SNI兼容补丁仅核验过httpcore 1.0.9")
    original = AsyncTunnelHTTPConnection.handle_async_request

    async def handle(self, request):
        """CONNECT仍指向已验证IP，仅把TLS握手恢复为真实主机名。"""
        hostname = request.extensions.get("sni_hostname")
        host_header = next(
            (value.decode("ascii") for key, value in request.headers if key.lower() == b"host"),
            None,
        )
        try:
            ipaddress.ip_address(self._remote_origin.host.decode("ascii"))
            pinned_ip = True
        except ValueError:
            pinned_ip = False
        if not self._connected and pinned_ip and hostname and hostname == host_header:
            # 每条连接独立SSLContext，避免改变共享上下文或其他OIDC请求的主机名。
            context = ssl.create_default_context(cafile=certifi.where())
            wrap_bio = context.wrap_bio

            def wrap(incoming, outgoing, server_side=False, server_hostname=None, session=None):
                """保留CERT_REQUIRED和check_hostname，让证书匹配已验证的原主机名。"""
                return wrap_bio(
                    incoming,
                    outgoing,
                    server_side=server_side,
                    server_hostname=hostname,
                    session=session,
                )

            context.wrap_bio = wrap
            self._ssl_context = context
        return await original(self, request)

    AsyncTunnelHTTPConnection.handle_async_request = handle
    _installed = True
