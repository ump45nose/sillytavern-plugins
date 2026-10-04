"""公网验收使用公共 TCP DNS，保留目标域名的 Host、SNI 和证书校验。"""

import ipaddress

import dns.resolver
import httpx


class PublicTransport(httpx.HTTPTransport):
    def __init__(self, hostname, address):
        super().__init__(trust_env=False)
        self.hostname = hostname
        self.address = address

    def handle_request(self, request):
        if request.url.host != self.hostname:
            raise ValueError("公网探针不允许跳转到其他主机")
        pinned = httpx.Request(request.method,
            request.url.copy_with(host=self.address), headers=request.headers,
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": self.hostname})
        return super().handle_request(pinned)


def public_transport(hostname):
    # 不修改宿主机 resolver。NAS 的本地 DNS 可能将自家域名映射回旧 DDNS。
    for nameserver in ("1.1.1.1", "8.8.8.8"):
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = [nameserver]
        resolver.timeout = 3
        resolver.lifetime = 5
        try:
            answer = resolver.resolve(hostname, "A", tcp=True)
            address = next(str(item) for item in answer
                           if ipaddress.ip_address(str(item)).is_global)
            return PublicTransport(hostname, address)
        except (dns.exception.DNSException, StopIteration):
            continue
    raise httpx.ConnectError("公共 DNS 未返回可用公网地址")
