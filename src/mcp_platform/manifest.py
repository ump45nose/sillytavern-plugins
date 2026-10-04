"""版本化应用清单及宿主机目标；目标文件始终位于业务仓库之外。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Volume(BaseModel):
    name: str
    mount: str
    external: bool = False


class AuthSpec(BaseModel):
    client_id: str
    discovery_url: str
    authorization_policy: str = "smartsearch_yuwk"
    claims_policy: str = "smartsearch_identity"
    secret_env: str = "OIDC_CLIENT_SECRET"
    generated_secret_envs: list[str] = Field(default_factory=lambda: [
        "OAUTH_JWT_SIGNING_KEY", "OAUTH_STORAGE_ENCRYPTION_KEY",
    ])
    usernames_env: str = "OIDC_AUTHORIZED_USERNAMES"
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "offline_access"])


class PluginSpec(BaseModel):
    name: str
    version: str
    description: str
    display_name: str
    app_id: str = ""
    app_binding: str = ""
    logo: str = ""
    keywords: list[str] = Field(default_factory=list)


class AppManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    name: str
    command: list[str]
    public_url: str
    port: int = Field(default=8080, ge=1, le=65535)
    host_port: int = Field(ge=1, le=65535)
    bind_address: str = "127.0.0.1"
    health_path: str = "/healthz"
    compose_project: str = ""
    compose_service: str = "app"
    volumes: list[Volume] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    required_env: list[str] = Field(default_factory=list)
    auth: AuthSpec
    backup_command: list[str] = Field(default_factory=list)
    integrity_command: list[str] = Field(default_factory=list)
    migration_command: list[str] = Field(default_factory=list)
    plugin: PluginSpec | None = None

    @model_validator(mode="after")
    def check(self):
        if self.schema_version != 1:
            raise ValueError("只支持清单 schema_version: 1")
        p = urlsplit(self.public_url)
        if p.scheme != "https" or not p.hostname or p.path not in ("", "/") or p.query or p.fragment or p.username:
            raise ValueError("public_url 必须是 HTTPS 独立域名根地址")
        if not self.command:
            raise ValueError("command 不能为空")
        self.public_url = self.public_url.rstrip("/")
        return self

    @property
    def hostname(self):
        return urlsplit(self.public_url).hostname

    @property
    def runtime_environment(self):
        return {**self.environment, "PUBLIC_BASE_URL": self.public_url,
                "OIDC_DISCOVERY_URL": self.auth.discovery_url,
                "OIDC_CLIENT_ID": self.auth.client_id}


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_roots: dict[str, str] = Field(default_factory=dict)
    env_files: dict[str, str] = Field(default_factory=dict)
    runtime_root: str
    build_user: str = "yuwk"
    uv: str = "/home/yuwk/.local/bin/uv"
    platform_repo: str = "/home/yuwk/mcp-platform"
    tunnel_config: str
    tunnel_compose: str
    tunnel_container: str = "local-env-mcp-cloudflared"
    tunnel_id: str
    authelia_config: str
    authelia_container: str = "authelia"
    cloudflare_env: str
    cloudflare_zone_id: str = ""
    ddns_config: str = ""
    ddns_container: str = "ddns-go"
    authorized_usernames: list[str] = Field(default_factory=lambda: ["yuwk"])


def read_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def load_target(path: Path, name: str) -> Target:
    result = Target.model_validate(read_yaml(path)["targets"][name])
    return result


def load_app(source: Path) -> AppManifest:
    return AppManifest.model_validate(read_yaml(source / "mcp.app.yaml"))


def private_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # 创建时即设置权限，避免短暂暴露；同目录原子替换。
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, path)


def template_yaml(text: str):
    return yaml.safe_load(re.sub(r"\{\{.*?\}\}", '"TEMPLATE_PLACEHOLDER"', text))
