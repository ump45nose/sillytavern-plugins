"""OIDC 装配和基于已验证上游身份的业务权限。"""

from __future__ import annotations

import hmac
from pathlib import Path
from typing import Literal

from key_value.aio.stores.disk import DiskStore
from key_value.aio.stores.filetree import (
    FileTreeStore,
    FileTreeV1CollectionSanitizationStrategy,
    FileTreeV1KeySanitizationStrategy,
)
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from .compat import PlatformOIDCProxy
from .config import RuntimeConfig


def claims(token) -> dict:
    raw = getattr(token, "claims", None)
    if not isinstance(raw, dict):
        return {}
    upstream = raw.get("upstream_claims")
    # 上游已验证声明是身份来源，不能被代理外层同名字段覆盖。
    return {**raw, **upstream} if isinstance(upstream, dict) else raw


def authorize(permission: Literal["read", "write", "execute"], config: RuntimeConfig):
    if permission not in {"read", "write", "execute"}:
        raise ValueError("未知权限")
    if config.development_no_auth:
        return None

    def check(context) -> bool:
        username = claims(context.token).get("preferred_username")
        if not isinstance(username, str):
            return False

        def member(values):
            return any(hmac.compare_digest(username.encode(), v.encode()) for v in values)

        if not member(config.authorized_usernames):
            return False
        if permission == "read":
            return True
        if member(config.read_only_usernames):
            return False
        return permission == "write" or member(config.execute_usernames)

    return check


def build_provider(config: RuntimeConfig):
    if config.development_no_auth:
        return None, None
    if config.proxy_sni_compatibility:
        from .proxy_sni import install_proxy_sni_compatibility
        install_proxy_sni_compatibility()
    if config.client_storage is not None:
        # 注入的是完整后端（可包含加密）；不会再套一层改变既有格式。
        storage = config.client_storage
        raw = None
    else:
        directory = Path(config.storage_path)
        if directory.is_symlink():
            raise ValueError("OAuth 存储目录不能为符号链接")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        if config.storage_backend == "filetree":
            raw = FileTreeStore(
                data_directory=directory,
                key_sanitization_strategy=FileTreeV1KeySanitizationStrategy(directory),
                collection_sanitization_strategy=FileTreeV1CollectionSanitizationStrategy(directory),
            )
        else:
            raw = DiskStore(directory=directory, auto_create=False, max_size=64 * 1024 * 1024)
        storage = FernetEncryptionWrapper(
            raw, source_material=config.storage_encryption_key.get_secret_value(),
            salt=config.storage_salt, raise_on_decryption_error=True,
        )
    provider = PlatformOIDCProxy(
        config_url=config.oidc_discovery_url,
        client_id=config.oidc_client_id,
        client_secret=config.oidc_client_secret.get_secret_value(),
        base_url=config.public_base_url,
        resource_base_url=config.public_base_url,
        issuer_url=config.public_base_url,
        redirect_path="/auth/callback",
        required_scopes=["openid", "profile", "offline_access"],
        verify_id_token=True, allowed_client_redirect_uris=config.client_redirect_uris,
        client_storage=storage, jwt_signing_key=config.jwt_signing_key.get_secret_value(),
        token_endpoint_auth_method="client_secret_basic", require_authorization_consent=True,
        enable_cimd=True, forward_resource=False, token_expiry_threshold_seconds=30,
    )
    return provider, raw
