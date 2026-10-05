"""首次协调 Media OAuth 网关；共享配置经过校验、加锁及比较后写入。"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values

from mcp_platform.deploy import deployment_lock, rollback_journal
from mcp_platform.exposure import probe_existing, rpc_result
from mcp_platform.infra import (
    Journal,
    authelia_text,
    digest,
    restart_authelia,
    run,
    switch_tunnel,
    validate_authelia_candidate,
    validate_tunnel_candidate,
)
from mcp_platform.manifest import AppManifest, AuthSpec, load_target, private_write

SOURCE = Path("/home/yuwk/media-automation/apps/media-download-mcp")
INTEGRATION = Path(__file__).parent
RUNTIME = Path("/home/yuwk/.config/mcp-platform/media-download-gateway")
BACKEND_TOKEN = Path("/home/yuwk/.config/mcp-platform/media-download-mcp/secrets/access.token")
BASE_IMAGE = "sha256:05c8ddd875743c4635fb12ce5ac21b5c383055227aaa5b7d6064b3c1c7c1f888"


def bearer_probe(app, *, public=False):
    base = app.public_url if public else "http://127.0.0.1:8092"
    headers = {"Accept": "application/json, text/event-stream", "Host": app.hostname,
               "Authorization": "Bearer " + BACKEND_TOKEN.read_text().strip()}
    with httpx.Client(trust_env=False, timeout=20, headers=headers) as client:
        result = rpc_result(client.post(base + "/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "media-gateway-smoke", "version": "0.1.0"},
            },
        }))
        client.headers["MCP-Protocol-Version"] = result["protocolVersion"]
        tools = rpc_result(client.post(base + "/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }))
        assert {x["name"] for x in tools["tools"]} == set(app.expected_tools)


def main():
    if os.geteuid() != 0:
        raise PermissionError("首次网关部署使用 sudo -n")
    target = load_target(Path("/home/yuwk/.config/mcp-platform/targets.yaml"), "nas")
    with deployment_lock(target):
        deploy_locked(target)


def deploy_locked(target):
    manifest_path = SOURCE / "mcp.app.yaml"
    original_manifest = manifest_path.read_text()
    manifest_hash = digest(manifest_path)
    config = yaml.safe_load(original_manifest)
    if config["host_port"] not in (8091, 8092):
        raise RuntimeError("Media 入口已被外部改动，停止覆盖")
    config.update(authentication="oauth", port=8092, host_port=8092, health_path="/healthz")
    config["auth"] = AuthSpec(
        client_id="media-download-mcp",
        discovery_url="https://authelia-home.172906573.xyz/.well-known/openid-configuration",
    ).model_dump()
    config["environment"] = {
        **config.get("environment", {}), "MEDIA_BACKEND_URL": "http://127.0.0.1:8091/mcp",
        "MEDIA_BACKEND_HOST": "media-download-home.172906573.xyz",
        "MEDIA_BACKEND_TOKEN_FILE": "/secrets/backend.token",
        "MEDIA_LEGACY_BEARER_USERNAME": "yuwk",
    }
    app = AppManifest.model_validate(config)
    if run(["docker", "image", "inspect", "local/personal-crm:refresh-policy-0.1.3",
            "--format", "{{.Id}}"] ).strip() != BASE_IMAGE:
        raise RuntimeError("基础运行镜像摘要不一致")
    if not BACKEND_TOKEN.is_file() or BACKEND_TOKEN.stat().st_mode & 0o077:
        raise RuntimeError("必须复用原 600 权限后端令牌")
    RUNTIME.mkdir(parents=True, exist_ok=True, mode=0o700)
    (RUNTIME / "oauth").mkdir(exist_ok=True, mode=0o700)
    env_path = RUNTIME / "gateway.env"
    if env_path.exists():
        env = dict(dotenv_values(env_path))
        if any(not env.get(k) for k in ("OIDC_CLIENT_SECRET", "OAUTH_JWT_SIGNING_KEY", "OAUTH_STORAGE_ENCRYPTION_KEY")):
            raise RuntimeError("已有网关密钥不完整，拒绝替换")
    else:
        env = {k: secrets.token_urlsafe(48) for k in (
            "OIDC_CLIENT_SECRET", "OAUTH_JWT_SIGNING_KEY", "OAUTH_STORAGE_ENCRYPTION_KEY",
        )}
    env.update(app.runtime_environment)
    env.update(HOST="127.0.0.1", PORT="8092", MCP_DEVELOPMENT_NO_AUTH="false",
               OIDC_AUTHORIZED_USERNAMES=",".join(target.authorized_usernames),
               OAUTH_STORAGE_PATH="/data/oauth", OAUTH_STORAGE_SALT="media-download-oauth-v1",
               MCP_PROXY_SNI_COMPATIBILITY="true")
    private_write(env_path, "".join(f"{key}={value}\n" for key, value in env.items()))
    compose = ["env", "MEDIA_GATEWAY_RUNTIME_DIR=" + str(RUNTIME),
               "MEDIA_BACKEND_TOKEN_FILE=" + str(BACKEND_TOKEN), "docker", "compose",
               "--project-name", "mcp-platform-media-download", "-f", INTEGRATION / "compose.yaml"]
    root = Path(target.runtime_root) / app.id
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    release = root / "releases" / stamp
    release.mkdir(parents=True, mode=0o700)
    current_path = root / "current.json"
    previous = json.loads(current_path.read_text()) if current_path.exists() else None
    journal = Journal(release / "journal.json", {
        "app": app.id, "status": "preparing", "deployment_mode": "existing",
        "files": [], "previous": {"state": previous}, "source": str(SOURCE),
    })
    before_services = run([*compose, "ps", "--quiet"]).strip()
    try:
        auth_original = Path(target.authelia_config).read_text()
        tunnel_original = Path(target.tunnel_config).read_text()
        auth_candidate = authelia_text(auth_original, app, env)
        tunnel_config = yaml.safe_load(tunnel_original)
        route = next(x for x in tunnel_config["ingress"] if x.get("hostname") == app.hostname)
        if route["service"] not in ("http://127.0.0.1:8091", "http://127.0.0.1:8092"):
            raise RuntimeError("Media Tunnel 回源被外部改动，停止覆盖")
        route["service"] = "http://127.0.0.1:8092"
        tunnel_candidate = yaml.safe_dump(tunnel_config, sort_keys=False)
        if auth_candidate != auth_original:
            validate_authelia_candidate(target, auth_candidate)
        if tunnel_candidate != tunnel_original:
            validate_tunnel_candidate(target, tunnel_candidate)
        run([*compose, "config", "--quiet"])
        run([*compose, "up", "-d", "--no-build"])
        for _ in range(30):
            try:
                probe_existing(app, target)
                bearer_probe(app)
                break
            except (httpx.HTTPError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError("候选网关健康或协议冒烟失败")
        if journal.replace_file(Path(target.authelia_config), auth_candidate,
                                expected_hash=hashlib.sha256(auth_original.encode()).hexdigest()):
            restart_authelia(target)
        if journal.replace_file(Path(target.tunnel_config), tunnel_candidate,
                                expected_hash=hashlib.sha256(tunnel_original.encode()).hexdigest()):
            switch_tunnel(target)
        probe_existing(app, target, public=True)
        bearer_probe(app, public=True)
        journal.replace_file(manifest_path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                             expected_hash=manifest_hash)
        gateway_image = yaml.safe_load((INTEGRATION / "compose.yaml").read_text())["services"]["gateway"]["image"]
        journal.set(status="complete", gateway_image=run([
            "docker", "image", "inspect", gateway_image,
            "--format", "{{.Id}}"] ).strip())
        private_write(current_path, json.dumps({"journal": str(journal.path),
            "manifest_fingerprint": digest(manifest_path), "deployment_mode": "existing"}, indent=2))
        print("Media OAuth 网关部署完成：匿名拒绝、OAuth 发现、原 Bearer 初始化及四个工具枚举通过。")
    except Exception as error:
        private_write(release / "error.log", getattr(error, "diagnostic", str(error)))
        journal.set(status="failed")
        rollback_journal(app, target, journal)
        if not before_services:
            run([*compose, "down"])
        raise RuntimeError("网关部署失败，已恢复本次共享配置；私有记录：" + str(release)) from None

if __name__ == "__main__":
    main()
