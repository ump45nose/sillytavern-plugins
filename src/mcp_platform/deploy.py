"""单实例 NAS 部署；代码回退和持久化数据的恢复分开处理。"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml
from dotenv import dotenv_values

from .infra import (
    Cloudflare,
    Journal,
    authelia_text,
    ddns_text,
    restart_authelia,
    run,
    switch_tunnel,
    tunnel_text,
    validate_authelia_candidate,
    validate_tunnel_candidate,
)
from .manifest import private_write


@contextmanager
def deployment_lock(target):
    root = Path(target.runtime_root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "deployment.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("已有部署正在执行") from None
        yield


def compose_args(app, path):
    return ["docker", "compose", "--project-name", app.compose_project or app.id,
            "--file", str(path)]


def container_for(app):
    containers = run(["docker", "ps", "-aq", "--filter",
                      "label=com.docker.compose.project=" + (app.compose_project or app.id),
                      "--filter", "label=com.docker.compose.service=" + app.compose_service]).split()
    if len(containers) > 1:
        raise RuntimeError("发现多个同名业务容器，拒绝猜测部署目标")
    return containers[0] if containers else None


def compose_text(app, image, env_file):
    volumes = {v.name: ({"name": v.name, "external": True} if v.external else {"name": v.name})
               for v in app.volumes}
    service = {
        "image": image, "restart": "unless-stopped", "env_file": [str(env_file)],
        "environment": app.runtime_environment, "command": app.command,
        "ports": [f"{app.bind_address}:{app.host_port}:{app.port}"],
        "volumes": [f"{v.name}:{v.mount}" for v in app.volumes],
        "healthcheck": {"test": ["CMD", "python", "-c",
            f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{app.port}{app.health_path}', timeout=3)"],
            "interval": "30s", "timeout": "5s", "retries": 3, "start_period": "20s"},
        "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
    }
    return yaml.safe_dump({"services": {app.compose_service: service}, "volumes": volumes}, sort_keys=False)


def prepare_env(app, target):
    env_path = Path(target.env_files.get(app.id, str(Path(target.runtime_root) / app.id / "service.env")))
    new = not env_path.exists()
    env = dict(dotenv_values(env_path)) if not new else {}
    if new:
        import secrets
        env.update({k: secrets.token_urlsafe(48) for k in
                    [app.auth.secret_env, *app.auth.generated_secret_envs]})
        env[app.auth.usernames_env] = ",".join(target.authorized_usernames)
        env.update(app.runtime_environment)
        private_write(env_path, "".join(k + "=" + json.dumps(v) + "\n" for k, v in env.items()))
    if env_path.stat().st_mode & 0o077:
        raise ValueError("业务 env 文件必须为 600 权限")
    combined = {**env, **app.runtime_environment}
    missing = [k for k in app.required_env if not combined.get(k)]
    if missing:
        raise ValueError("业务凭据缺失: " + ", ".join(missing))
    if min(len(str(combined.get(k) or "")) for k in
           [app.auth.secret_env, *app.auth.generated_secret_envs]) < 32:
        raise ValueError("生产 OAuth 凭据缺失或过短")
    return env_path, combined


def build_bundle(app, source, target, destination):
    """宿主机解析私有 Git，容器只接收锁定依赖和 wheel。"""
    import tomllib
    destination.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        import pwd
        user = pwd.getpwnam(target.build_user)
        os.chown(destination, user.pw_uid, user.pw_gid)
    dirty = run(["git", "status", "--porcelain"], cwd=source, user=target.build_user)
    if dirty.strip():
        raise ValueError("业务仓库有未提交修改，请先提交以记录准确部署版本")
    source_sha = run(["git", "rev-parse", "HEAD"], cwd=source, user=target.build_user).strip()
    lock = tomllib.loads((source / "uv.lock").read_text())
    core = next((p for p in lock["package"] if p["name"] == "mcp-platform"), None)
    if not core or "git" not in core["source"]:
        raise ValueError("业务 uv.lock 必须锁定公共基座的 Git 提交")
    core_sha = core["source"]["git"].split("#")[-1]
    # 使用已认证的宿主机检出锁定提交；不把 .git 或凭据复制进容器。
    staging = destination / "platform-source"
    run(["git", "clone", "--no-checkout", target.platform_repo, staging], user=target.build_user)
    run(["git", "checkout", "--detach", core_sha], cwd=staging, user=target.build_user)
    wheels = destination / "wheels"
    run([target.uv, "build", "--wheel", "--out-dir", wheels], cwd=staging, user=target.build_user)
    run([target.uv, "build", "--wheel", "--out-dir", wheels], cwd=source, user=target.build_user)
    run([target.uv, "export", "--frozen", "--no-dev", "--no-emit-project",
         "--no-emit-package", "mcp-platform", "--output-file", destination / "requirements.txt"],
        cwd=source, user=target.build_user)
    shutil.rmtree(staging)
    (destination / "Dockerfile").write_text(
        "FROM python:3.12-slim\n"
        "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\n"
        "WORKDIR /app\nCOPY requirements.txt /app/requirements.txt\n"
        "RUN pip install --no-cache-dir uv==0.12.1 && uv pip install --system --require-hashes -r requirements.txt\n"
        "COPY wheels /app/wheels\nRUN uv pip install --system --no-deps /app/wheels/*.whl\n"
    )
    checksums = {str(p.relative_to(destination)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in [destination / "requirements.txt", *wheels.glob("*.whl")]}
    private_write(destination / "artifacts.json", json.dumps(checksums, indent=2))
    image = f"local/{app.id}:{source_sha[:12]}-platform-{core_sha[:12]}"
    run(["docker", "build", "--tag", image, destination], timeout=600)
    return image, source_sha, core_sha


def wait_health(app, *, public=False):
    url = app.public_url if public else f"http://{app.bind_address}:{app.host_port}"
    with httpx.Client(timeout=5, trust_env=public, follow_redirects=True) as client:
        for _ in range(24):
            try:
                health = client.get(url + app.health_path)
                health.raise_for_status()
                payload = health.json()
                if payload.get("status") != "ok" or payload.get("database", "ok") != "ok":
                    raise RuntimeError("业务健康检查未通过")
                denied = client.post(url + "/mcp", json={"jsonrpc": "2.0", "id": 1,
                    "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                    "capabilities": {}, "clientInfo": {"name": "mcpctl", "version": "0.1"}}},
                    headers={"Accept": "application/json, text/event-stream"})
                if denied.status_code != 401 or "resource_metadata" not in denied.headers.get("www-authenticate", ""):
                    raise RuntimeError("MCP 未认证请求未返回预期挑战")
                metadata = client.get(url + "/.well-known/oauth-protected-resource").json()
                auth = client.get(url + "/.well-known/oauth-authorization-server").json()
                if metadata.get("resource") != app.public_url + "/mcp" or auth.get("issuer") not in metadata.get("authorization_servers", []):
                    raise RuntimeError("OAuth 发现元数据与清单不一致")
                if auth.get("token_endpoint") != app.public_url + "/token" or "S256" not in auth.get("code_challenge_methods_supported", []):
                    raise RuntimeError("Token 地址或 PKCE 元数据不一致")
                return
            except (httpx.HTTPError, ValueError):
                time.sleep(2)
        raise RuntimeError("服务健康／发现检查超时")


def rollback_journal(app, target, journal):
    if journal.data.get("rollback_status") == "complete":
        return
    if journal.data.get("dns"):
        cf = Cloudflare(target)
        try:
            cf.restore(journal.data["dns"])
        finally:
            cf.client.close()
    restored = journal.restore_files()
    if target.tunnel_config in restored:
        switch_tunnel(target)
    if target.authelia_config in restored:
        restart_authelia(target)
    if target.ddns_config in restored:
        run(["docker", "restart", target.ddns_container])
    old = journal.data.get("previous")
    if old and journal.data.get("service_attempted"):
        run([*compose_args(app, old["rollback_compose"]), "up", "-d", "--no-deps", app.compose_service])
        wait_health(app)
    elif journal.data.get("service_attempted"):
        run([*compose_args(app, journal.data["compose"]), "rm", "--stop", "--force", app.compose_service])
    journal.set(rollback_status="complete")


def deploy(app, source, target):
    if os.geteuid() != 0:
        raise PermissionError("NAS 共享配置需要管理员权限；请用 sudo -n 运行 mcpctl deploy")
    with deployment_lock(target):
        deploy_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        root = Path(target.runtime_root) / app.id
        release = root / "releases" / deploy_id
        release.mkdir(parents=True, mode=0o700)
        # 构建子进程以普通用户运行，需要访问发布目录，但不开放秘密目录。
        import pwd
        builder = pwd.getpwnam(target.build_user)
        for p in (root.parent, root, root / "releases", release):
            p.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chown(p, builder.pw_uid, builder.pw_gid)
        journal = Journal(release / "journal.json", {"app": app.id, "id": deploy_id,
                           "status": "preparing", "files": []})
        cf = None
        try:
            env_path, env = prepare_env(app, target)
            auth_original = Path(target.authelia_config).read_text()
            tunnel_original = Path(target.tunnel_config).read_text()
            auth_candidate = authelia_text(auth_original, app, env)
            tunnel_candidate = tunnel_text(tunnel_original, app)
            ddns_original = Path(target.ddns_config).read_text() if target.ddns_config else None
            ddns_candidate = ddns_text(ddns_original, app.hostname) if ddns_original is not None else None
            cf = Cloudflare(target)
            cf.find_zone(app.hostname)
            cf.records(app.hostname)  # 凭据与域名预检先于服务更新。
            current = root / "current.json"
            previous_state = json.loads(current.read_text()) if current.exists() else None
            source_sha = run(["git", "rev-parse", "HEAD"], cwd=source, user=target.build_user).strip()
            old_id = container_for(app)
            old_container = json.loads(run(["docker", "inspect", old_id]))[0] if old_id else None
            env_fingerprint = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
            if previous_state and previous_state["source_sha"] == source_sha and previous_state["env_fingerprint"] == env_fingerprint and old_container and old_container["Image"] == previous_state["image_id"]:
                # 重复部署仍校验公网和共享配置；不重复重启或生成新密钥。
                if auth_candidate == auth_original and tunnel_candidate == tunnel_original and ddns_candidate == ddns_original:
                    records = cf.records(app.hostname)
                    if len(records) == 1 and records[0]["content"] == target.tunnel_id + ".cfargotunnel.com" and records[0].get("proxied"):
                        wait_health(app, public=True)
                        journal.set(status="unchanged")
                        print("版本和配置已一致，验证通过；未更新服务")
                        return journal.path
            if auth_candidate != auth_original:
                validate_authelia_candidate(target, auth_candidate)
            if tunnel_candidate != tunnel_original:
                validate_tunnel_candidate(target, tunnel_candidate)
            image, source_sha, core_sha = build_bundle(app, source, target, release / "build")
            new_compose = release / "compose.yaml"
            private_write(new_compose, compose_text(app, image, env_path))
            run([*compose_args(app, new_compose), "config", "--quiet"])
            journal.set(image=image, source_sha=source_sha, core_sha=core_sha, compose=str(new_compose))
            if old_container:
                rollback_file = release / "rollback-compose.yaml"
                if previous_state:
                    previous_config = yaml.safe_load(Path(previous_state["compose"]).read_text())
                    previous_config["services"][app.compose_service]["image"] = old_container["Image"]
                    previous_compose = yaml.safe_dump(previous_config, sort_keys=False)
                else:
                    old_compose_path = old_container["Config"]["Labels"]["com.docker.compose.project.config_files"]
                    # 旧配置的相对 .env、构建目录转换成绝对路径；镜像锁定原 digest。
                    old_config = yaml.safe_load(Path(old_compose_path).read_text())
                    old_service = old_config["services"][app.compose_service]
                    old_service.pop("build", None)
                    old_service["image"] = old_container["Image"]
                    old_service["env_file"] = [str(env_path)]
                    old_service["ports"] = [f"{app.bind_address}:{app.host_port}:{app.port}"]
                    previous_compose = yaml.safe_dump(old_config, sort_keys=False)
                private_write(rollback_file, previous_compose)
                journal.set(previous={"image": old_container["Image"], "rollback_compose": str(rollback_file),
                                      "state": previous_state})
                # SQLite 在线备份使用标准 backup API，避免仅复制 WAL 主文件。
                if app.backup_command:
                    backup_in_container = f"/data/mcp-platform-backup-{deploy_id}.db"
                    command = [x.replace("{backup_path}", backup_in_container) for x in app.backup_command]
                    run(["docker", "exec", old_id, *command])
                    run(["docker", "cp", old_id + ":" + backup_in_container, release / "database-backup.db"])
                    os.chmod(release / "database-backup.db", 0o600)
                    run(["docker", "exec", old_id, "python", "-c",
                         "from pathlib import Path;Path(" + repr(backup_in_container) + ").unlink()"])
                oauth_path = str(env.get("OAUTH_STORAGE_PATH") or "/data/oauth")
                run(["docker", "exec", old_id, "python", "-c",
                     "import tarfile;from pathlib import Path;f=tarfile.open('/tmp/mcp-platform-oauth.tar','w');"
                     + f"p=Path({oauth_path!r});f.add(p,arcname='oauth') if p.exists() else None;f.close()"])
                run(["docker", "cp", old_id + ":/tmp/mcp-platform-oauth.tar", release / "oauth-backup.tar"])
                os.chmod(release / "oauth-backup.tar", 0o600)
                run(["docker", "exec", old_id, "python", "-c",
                     "from pathlib import Path;Path('/tmp/mcp-platform-oauth.tar').unlink()"])
            # 共享文件均写入日志后应用，失败只恢复记录的变更。
            if journal.replace_file(Path(target.authelia_config), auth_candidate,
                                    expected_hash=hashlib.sha256(auth_original.encode()).hexdigest()):
                restart_authelia(target)
            journal.set(service_attempted=True)
            run([*compose_args(app, new_compose), "up", "-d", "--no-deps", app.compose_service])
            wait_health(app)
            if app.integrity_command:
                run(["docker", "exec", container_for(app), *app.integrity_command])
            if app.migration_command:
                # 显式命令；失败不自动恢复数据库，防止覆盖部署期间写入。
                run(["docker", "exec", container_for(app), *app.migration_command])
            if journal.replace_file(Path(target.tunnel_config), tunnel_candidate,
                                    expected_hash=hashlib.sha256(tunnel_original.encode()).hexdigest()):
                switch_tunnel(target)
            if target.ddns_config:
                ddns_path = Path(target.ddns_config)
                if journal.replace_file(ddns_path, ddns_candidate,
                                        expected_hash=hashlib.sha256(ddns_original.encode()).hexdigest()):
                    run(["docker", "restart", target.ddns_container])
            cf.switch(app, target, journal)
            wait_health(app, public=True)
            image_id = json.loads(run(["docker", "inspect", container_for(app)]))[0]["Image"]
            journal.set(status="complete", image_id=image_id, env_fingerprint=env_fingerprint)
            private_write(current, json.dumps({k: journal.data[k] for k in
                          ("source_sha", "core_sha", "image", "image_id", "compose", "env_fingerprint")} |
                          {"journal": str(journal.path)}, indent=2))
            print(f"部署完成: {app.public_url}/mcp；记录: {journal.path}")
        except Exception as error:
            private_write(release / "error.log", getattr(error, "diagnostic", str(error)))
            journal.set(status="failed")
            try:
                rollback_journal(app, target, journal)
            except Exception as rollback_error:
                private_write(release / "rollback-error.log", getattr(rollback_error, "diagnostic", str(rollback_error)))
                journal.set(rollback_status="needs_attention")
                raise RuntimeError(f"部署失败，回滚需处理；私有记录: {journal.path}") from None
            raise RuntimeError(f"部署失败，本次变更已回滚；私有记录: {journal.path}") from None
        finally:
            if cf:
                cf.client.close()
        return journal.path
