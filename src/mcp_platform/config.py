"""显式运行配置；不从不完整配置推断生产服务可以匿名运行。"""

from __future__ import annotations

import ipaddress
import os
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    name: str
    version: str = "0.1.0"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65535)
    development_no_auth: bool = False
    public_base_url: str = ""
    oidc_discovery_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: SecretStr = SecretStr("")
    jwt_signing_key: SecretStr = SecretStr("")
    storage_encryption_key: SecretStr = SecretStr("")
    storage_path: str = "/data/oauth"
    storage_backend: Literal["filetree", "disk"] = "filetree"
    storage_salt: str = "mcp-platform-oauth-v1"
    client_storage: Any = Field(default=None, exclude=True)
    authorized_usernames: set[str] = Field(default_factory=set)
    read_only_usernames: set[str] = Field(default_factory=set)
    execute_usernames: set[str] = Field(default_factory=set)
    client_redirect_uris: list[str] = Field(default_factory=lambda: [
        "http://localhost:*", "http://127.0.0.1:*", "https://chatgpt.com/*",
    ])
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    allowed_origins: list[str] = Field(default_factory=lambda: ["https://chatgpt.com"])
    proxy_sni_compatibility: bool = False
    audit_enabled: bool = True
    requests_per_minute: int = Field(default=60, ge=0)
    tool_timeout_seconds: float = Field(default=60, ge=0)
    max_output_bytes: int = Field(default=256_000, ge=0)

    @classmethod
    def from_env(cls, name: str):
        def csv(key):
            return [x.strip() for x in os.getenv(key, "").split(",") if x.strip()]
        values = {
            "name": name, "host": os.getenv("HOST", "127.0.0.1"),
            "port": int(os.getenv("PORT", "8080")),
            "development_no_auth": os.getenv("MCP_DEVELOPMENT_NO_AUTH", "false").lower() == "true",
            "public_base_url": os.getenv("PUBLIC_BASE_URL", ""),
            "oidc_discovery_url": os.getenv("OIDC_DISCOVERY_URL", ""),
            "oidc_client_id": os.getenv("OIDC_CLIENT_ID", ""),
            "oidc_client_secret": os.getenv("OIDC_CLIENT_SECRET", ""),
            "jwt_signing_key": os.getenv("OAUTH_JWT_SIGNING_KEY", ""),
            "storage_encryption_key": os.getenv("OAUTH_STORAGE_ENCRYPTION_KEY", ""),
            "storage_path": os.getenv("OAUTH_STORAGE_PATH", "/data/oauth"),
            "storage_salt": os.getenv("OAUTH_STORAGE_SALT", name + "-oauth-v1"),
            "storage_backend": os.getenv("OAUTH_STORAGE_BACKEND", "filetree"),
            "authorized_usernames": set(csv("OIDC_AUTHORIZED_USERNAMES")),
            "read_only_usernames": set(csv("OIDC_READ_ONLY_USERNAMES")),
            "execute_usernames": set(csv("OIDC_EXECUTE_USERNAMES")),
            "proxy_sni_compatibility": os.getenv("MCP_PROXY_SNI_COMPATIBILITY", "false").lower() == "true",
        }
        if csv("ALLOWED_CLIENT_REDIRECT_URIS"):
            values["client_redirect_uris"] = csv("ALLOWED_CLIENT_REDIRECT_URIS")
        return cls(**values)

    @model_validator(mode="after")
    def validate_security(self):
        if self.development_no_auth:
            if self.host != "localhost":
                try:
                    loopback = ipaddress.ip_address(self.host).is_loopback
                except ValueError:
                    loopback = False
                if not loopback:
                    raise ValueError("无认证开发模式只能绑定回环地址")
            if self.public_base_url:
                raise ValueError("无认证开发模式不能配置公网地址")
            return self
        for value in (self.public_base_url, self.oidc_discovery_url):
            p = urlsplit(value)
            if p.scheme != "https" or not p.hostname or p.username or p.query or p.fragment:
                raise ValueError("生产公网地址和 OIDC discovery 必须为完整 HTTPS URL")
        if not self.oidc_client_id or not self.oidc_client_secret.get_secret_value():
            raise ValueError("生产 OIDC 客户端凭据不完整")
        if not self.authorized_usernames:
            raise ValueError("生产身份白名单不能为空")
        if min(len(self.jwt_signing_key.get_secret_value()),
               len(self.storage_encryption_key.get_secret_value())) < 32:
            raise ValueError("OAuth 签名和存储密钥至少需要 32 个字符")
        self.public_base_url = self.public_base_url.rstrip("/")
        return self
