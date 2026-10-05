"""版本化应用清单及宿主机目标；目标文件始终位于业务仓库之外。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Volume(BaseModel):
    name: str
    mount: str
    external: bool = False


class BindMount(BaseModel):
    """只读挂载既有数据目录，不授予容器写宿主机文件的权限。"""

    model_config = ConfigDict(extra="forbid")
    source: str
    mount: str
    read_only: Literal[True] = True

    @model_validator(mode="after")
    def check_paths(self):
        for value in (self.source, self.mount):
            path = Path(value)
            if not path.is_absolute() or ".." in path.parts or value == "/":
                raise ValueError("只读绑定挂载必须使用非根目录的绝对路径")
        return self


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
    short_description: str | None = Field(default=None, min_length=1, max_length=30)
    brand_color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    app_id: str = ""
    app_binding: str = ""
    logo: str = ""
    keywords: list[str] = Field(default_factory=list)


class AppManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = 1
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    name: str
    deployment_mode: Literal["build", "existing"] = "build"
    authentication: Literal["oauth", "bearer"] = "oauth"
    oauth_provider: Literal["authelia", "mcphub"] = "authelia"
    refresh_token_lifetime_days: int = Field(default=180, ge=1, strict=True)
    command: list[str] = Field(default_factory=list)
    public_url: str
    port: int = Field(default=8080, ge=1, le=65535)
    host_port: int = Field(ge=1, le=65535)
    bind_address: str = "127.0.0.1"
    health_path: str = "/healthz"
    mcp_path: str = "/mcp"
    expected_tools: list[str] = Field(default_factory=list)
    compose_project: str = ""
    compose_service: str = "app"
    user: str = ""
    working_dir: str = ""
    init: bool = False
    external_networks: list[str] = Field(default_factory=list)
    volumes: list[Volume] = Field(default_factory=list)
    bind_mounts: list[BindMount] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    required_env: list[str] = Field(default_factory=list)
    auth: AuthSpec | None = None
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
        if self.deployment_mode == "build" and (not self.command or self.auth is None):
            raise ValueError("构建模式必须提供 command 和 auth")
        if self.deployment_mode == "build" and self.authentication != "oauth":
            raise ValueError("公共运行时构建模式使用 OAuth")
        if self.deployment_mode == "build" and self.mcp_path != "/mcp":
            raise ValueError("公共运行时构建模式目前使用 /mcp")
        if not self.mcp_path.startswith("/") or self.mcp_path.startswith("//") or "?" in self.mcp_path:
            raise ValueError("mcp_path 必须是本服务的绝对路径")
        if self.health_path and (not self.health_path.startswith("/") or self.health_path.startswith("//")):
            raise ValueError("health_path 必须是本服务的绝对路径")
        self.public_url = self.public_url.rstrip("/")
        return self

    @property
    def hostname(self):
        return urlsplit(self.public_url).hostname

    @property
    def runtime_environment(self):
        if self.auth is None:
            return dict(self.environment)
        return {**self.environment,
                "OAUTH_REFRESH_TOKEN_LIFETIME_DAYS": str(self.refresh_token_lifetime_days),
                "PUBLIC_BASE_URL": self.public_url,
                "OIDC_DISCOVERY_URL": self.auth.discovery_url,
                "OIDC_CLIENT_ID": self.auth.client_id}


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_roots: dict[str, str] = Field(default_factory=dict)
    env_files: dict[str, str] = Field(default_factory=dict)
    probe_token_files: dict[str, str] = Field(default_factory=dict)
    compose_files: dict[str, str] = Field(default_factory=dict)
    compose_files: dict[str, str] = Field(default_factory=dict)
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
    mcphub_config: str = ""
    mcphub_container: str = "mcphub"
    auth_runtime_env_files: dict[str, str] = Field(default_factory=dict)
    auth_reload_commands: dict[str, list[str]] = Field(default_factory=dict)
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
