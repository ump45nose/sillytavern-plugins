"""将已有 MCP 进程接入共享 Tunnel，不变更业务运行时和认证。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .deploy import deployment_lock, rollback_journal
from .infra import (
    Cloudflare,
    Journal,
    ddns_text,
    run,
    switch_tunnel,
    tunnel_text,
    validate_tunnel_candidate,
)
from .manifest import private_write


def rpc_result(response):
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        messages = [json.loads(line[5:].strip()) for line in response.text.splitlines()
                    if line.startswith("data:")]
        payload = next((item for item in messages if "result" in item or "error" in item), {})
    else:
        payload = response.json()
    if "error" in payload or "result" not in payload:
        raise RuntimeError("MCP 协议响应未成功")
    return payload["result"]


def probe_existing(app, target, *, public=False):
    base = app.public_url if public else f"http://{app.bind_address}:{app.host_port}"
    headers = {"Accept": "application/json, text/event-stream"}
    if not public:
        headers.update(Host=app.hostname, **{"X-Forwarded-Proto": "https"})
    # 不让 NAS 的出口代理影响回环、LAN 或公网入口验证。
    with httpx.Client(timeout=15, trust_env=False, headers=headers) as client:
        if app.health_path:
            health = client.get(base + app.health_path)
            health.raise_for_status()
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "mcp-platform-tunnel-smoke", "version": "0.1.2"}}}
        denied = client.post(base + app.mcp_path, json=initialize)
        if denied.status_code != 401:
            raise RuntimeError("已有 MCP 未认证请求必须返回 401")
        if app.authentication == "oauth":
            challenge = denied.headers.get("www-authenticate", "")
            match = re.search(r'resource_metadata="([^"]+)"', challenge)
            if not match or not match[1].startswith(app.public_url + "/"):
                raise RuntimeError("OAuth 资源发现挑战与应用入口不一致")
            path = match[1][len(app.public_url):]
            resource = client.get(base + path)
            resource.raise_for_status()
            metadata = resource.json()
            if metadata.get("resource", "").rstrip("/") not in {app.public_url, app.public_url + app.mcp_path}:
                raise RuntimeError("OAuth resource 与应用入口不一致")
            authorization = client.get(base + "/.well-known/oauth-authorization-server")
            authorization.raise_for_status()
            issuer = authorization.json().get("issuer", "")
            if issuer.rstrip("/") != app.public_url or issuer not in metadata.get("authorization_servers", []):
                raise RuntimeError("OAuth issuer 与原入口不一致")
        else:
            token_path = Path(target.probe_token_files.get(app.id, ""))
            if not token_path.is_file() or token_path.stat().st_mode & 0o077:
                raise ValueError("Bearer 服务必须配置仓库外 600 权限的 probe_token_files")
            token = token_path.read_text().strip()
            if not token or "\n" in token or "\r" in token:
                raise ValueError("Bearer 验证令牌无效")
            authorized = {"Authorization": "Bearer " + token}
            initialized = client.post(base + app.mcp_path, json=initialize, headers=authorized)
            result = rpc_result(initialized)
            if not result.get("protocolVersion") or not result.get("serverInfo"):
                raise RuntimeError("MCP initialize 返回无效")
            if initialized.headers.get("mcp-session-id"):
                authorized["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
            authorized["MCP-Protocol-Version"] = result["protocolVersion"]
            client.post(base + app.mcp_path, headers=authorized,
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            tools = rpc_result(client.post(base + app.mcp_path, headers=authorized,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
            if not set(app.expected_tools) <= {tool["name"] for tool in tools.get("tools", [])}:
                raise RuntimeError("MCP 工具枚举缺少清单声明的工具")


def wait_public_probe(app, target):
    """新 DNS 记录可能暂时命中旧通配 DDNS；始终保留 TLS 验证。"""
    deadline = time.monotonic() + 300
    announced = False
    while True:
        try:
            probe_existing(app, target, public=True)
            return
        except (httpx.ConnectError, httpx.TimeoutException):
            if time.monotonic() >= deadline:
                raise RuntimeError("公网 DNS／TLS 在五分钟内未就绪，恢复本次入口变更") from None
            if not announced:
                print("等待公网 DNS／TLS 传播；证书验证保持启用", flush=True)
                announced = True
            time.sleep(5)


def deploy_existing(app, source, target):
    if os.geteuid() != 0:
        raise PermissionError("共享 Tunnel 配置需要 sudo -n 权限")
    with deployment_lock(target):
        fingerprint = hashlib.sha256((source / "mcp.app.yaml").read_bytes()).hexdigest()
        root = Path(target.runtime_root) / app.id
        release = root / "releases" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        release.mkdir(parents=True, mode=0o700)
        journal = Journal(release / "journal.json", {"app": app.id, "status": "preparing",
                          "deployment_mode": "existing", "manifest_fingerprint": fingerprint,
                          "files": [], "source": str(source)})
        current_path = root / "current.json"
        previous = json.loads(current_path.read_text()) if current_path.exists() else None
        journal.set(previous={"state": previous})
        cf = None
        try:
            probe_existing(app, target)
            original = Path(target.tunnel_config).read_text()
            candidate = tunnel_text(original, app)
            ddns_original = Path(target.ddns_config).read_text() if target.ddns_config else None
            ddns_candidate = ddns_text(ddns_original, app.hostname) if ddns_original is not None else None
            cf = Cloudflare(target)
            cf.find_zone(app.hostname)
            records = cf.records(app.hostname)
            desired = len(records) == 1 and records[0]["type"] == "CNAME" and records[0]["content"] == target.tunnel_id + ".cfargotunnel.com" and records[0].get("proxied")
            if candidate != original:
                validate_tunnel_candidate(target, candidate)
            if journal.replace_file(Path(target.tunnel_config), candidate,
                                    expected_hash=hashlib.sha256(original.encode()).hexdigest()):
                switch_tunnel(target)
            if target.ddns_config and journal.replace_file(Path(target.ddns_config), ddns_candidate,
                                      expected_hash=hashlib.sha256(ddns_original.encode()).hexdigest()):
                run(["docker", "restart", target.ddns_container])
            cf.switch(app, target, journal)
            wait_public_probe(app, target)
            if previous and previous.get("manifest_fingerprint") == fingerprint and desired and not journal.data["files"]:
                journal.set(status="unchanged")
                print("入口和清单已一致，验证通过；未更新业务、认证或 Tunnel")
                return journal.path
            journal.set(status="complete")
            private_write(current_path, json.dumps({"journal": str(journal.path),
                          "manifest_fingerprint": fingerprint, "deployment_mode": "existing"}, indent=2))
            print(f"Tunnel 接入完成: {app.public_url}{app.mcp_path}；记录: {journal.path}")
        except Exception as error:
            private_write(release / "error.log", getattr(error, "diagnostic", str(error)))
            journal.set(status="failed")
            try:
                rollback_journal(app, target, journal)
            except Exception as rollback_error:
                private_write(release / "rollback-error.log", getattr(rollback_error, "diagnostic", str(rollback_error)))
                journal.set(rollback_status="needs_attention")
                raise RuntimeError(f"入口更新失败，回滚需处理；私有记录: {journal.path}") from None
            raise RuntimeError(f"入口更新失败，已恢复本次变更；私有记录: {journal.path}") from None
        finally:
            if cf:
                cf.client.close()
        return journal.path
