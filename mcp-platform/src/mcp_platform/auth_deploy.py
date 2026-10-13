"""部署清单的刷新期限协调；保留客户端身份和 OAuth 动态状态。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from .infra import Journal, authelia_text, restart_authelia, run, validate_authelia_candidate
from .manifest import private_write


@dataclass
class AuthChange:
    provider: str
    path: Path
    original: str
    candidate: str
    seconds: int
    app_id: str = ""
    runtime_path: Path | None = None
    runtime_original: str = ""
    runtime_candidate: str = ""

    @property
    def changed(self):
        return self.original != self.candidate or self.runtime_original != self.runtime_candidate


def runtime_binding(change, app, target):
    change.app_id = app.id
    path = target.auth_runtime_env_files.get(app.id)
    if not path:
        return change
    change.runtime_path = Path(path)
    change.runtime_original = change.runtime_path.read_text()
    current = dotenv_values(change.runtime_path).get("OAUTH_REFRESH_TOKEN_LIFETIME_DAYS", "180")
    change.runtime_candidate = change.runtime_original
    if current != str(app.refresh_token_lifetime_days):
        if not target.auth_reload_commands.get(app.id):
            raise ValueError("运行时期限变化需要在目标配置登记 auth_reload_commands")
        line = f"OAUTH_REFRESH_TOKEN_LIFETIME_DAYS={app.refresh_token_lifetime_days}\n"
        pattern = r"(?m)^OAUTH_REFRESH_TOKEN_LIFETIME_DAYS=.*(?:\n|$)"
        if re.search(pattern, change.runtime_original):
            change.runtime_candidate = re.sub(pattern, line, change.runtime_original)
        else:
            change.runtime_candidate = change.runtime_original.rstrip("\n") + "\n" + line
    return change


def prepare_auth_change(app, target, env=None):
    if app.authentication != "oauth":
        return None
    seconds = app.refresh_token_lifetime_days * 86400
    if app.oauth_provider == "authelia":
        if app.auth is None:
            return None
        path = Path(target.authelia_config)
        original = path.read_text()
        return runtime_binding(AuthChange("authelia", path, original,
                          authelia_text(original, app, env or {}), seconds), app, target)
    if not target.mcphub_config:
        raise ValueError("MCPHub 认证需要在目标文件登记 mcphub_config")
    path = Path(target.mcphub_config)
    original = path.read_text()
    config = json.loads(original)
    server = config["systemConfig"]["oauthServer"]
    if not server.get("enabled") or not isinstance(server.get("refreshTokenLifetime"), int):
        raise ValueError("必须复用已经启用的 MCPHub 北向 OAuth")
    if server["refreshTokenLifetime"] == seconds:
        candidate = original
    else:
        server["refreshTokenLifetime"] = seconds
        candidate = json.dumps(config, ensure_ascii=False, indent=2)
    return AuthChange("mcphub", path, original, candidate, seconds)


def validate_auth_change(change, target):
    if change and change.original != change.candidate and change.provider == "authelia":
        validate_authelia_candidate(target, change.candidate)


def apply_auth_change(change, target, journal):
    if not change or not change.changed:
        return False
    expected_hash = hashlib.sha256(change.original.encode()).hexdigest()
    if change.provider == "authelia":
        if journal.replace_file(change.path, change.candidate, expected_hash=expected_hash):
            restart_authelia(target)
    else:
        # 同一文件保存令牌，停止进程后仅修改配置字段，避免并发写入。
        run(["docker", "stop", "--time", "15", target.mcphub_container])
        try:
            journal.replace_json_value(change.path,
                ["systemConfig", "oauthServer", "refreshTokenLifetime"],
                change.seconds, expected_hash=expected_hash)
        finally:
            run(["docker", "start", target.mcphub_container])
    if change.runtime_path and change.runtime_original != change.runtime_candidate:
        journal.replace_file(change.runtime_path, change.runtime_candidate,
            expected_hash=hashlib.sha256(change.runtime_original.encode()).hexdigest())
        journal.set(auth_runtime_app=change.app_id)
        run(target.auth_reload_commands[change.app_id])
    journal.set(oauth_provider=change.provider, refresh_token_lifetime_seconds=change.seconds)
    return True


def restore_auth_json(target, journal):
    if not journal.data.get("json_values"):
        return
    run(["docker", "stop", "--time", "15", target.mcphub_container])
    try:
        journal.restore_json_values()
    finally:
        run(["docker", "start", target.mcphub_container])


def deploy_auth_only(app, source, target):
    from .deploy import deployment_lock, rollback_journal

    if os.geteuid() != 0:
        raise PermissionError("认证配置部署需要 sudo -n")
    with deployment_lock(target):
        change = prepare_auth_change(app, target)
        if change is None:
            raise ValueError("清单未登记受管理的 OAuth 提供方／客户端")
        root = Path(target.runtime_root) / app.id
        release = root / "releases" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + "-auth")
        current_path = root / "auth-current.json"
        previous = json.loads(current_path.read_text()) if current_path.exists() else None
        journal = Journal(release / "journal.json", {
            "app": app.id, "source": str(source), "deployment_mode": "auth-only",
            "status": "preparing", "files": [], "previous": {"state": previous},
            "refresh_token_lifetime_days": app.refresh_token_lifetime_days,
        })
        try:
            validate_auth_change(change, target)
            updated = apply_auth_change(change, target, journal)
            journal.set(status="complete" if updated else "unchanged")
            if updated:
                private_write(current_path, json.dumps({"journal": str(journal.path)}, indent=2))
            print(f"{app.id}: 刷新期限 {app.refresh_token_lifetime_days} 天；"
                  + ("认证配置已更新" if updated else "配置一致，未重启"))
        except Exception as error:
            private_write(release / "error.log", getattr(error, "diagnostic", str(error)))
            journal.set(status="failed")
            rollback_journal(app, target, journal)
            raise RuntimeError(f"认证配置更新失败，已恢复；私有记录: {journal.path}") from None
        return journal.path
