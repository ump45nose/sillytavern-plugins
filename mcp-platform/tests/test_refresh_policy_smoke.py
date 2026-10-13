"""刷新期限的必要冒烟：模板保留、默认／覆盖及状态不回退。"""

import json
from types import SimpleNamespace

import pytest

from mcp_platform.auth import build_provider
from mcp_platform.config import RuntimeConfig
from mcp_platform.infra import Journal, authelia_text, digest
from mcp_platform.manifest import AppManifest, template_yaml


def manifest(**changes):
    return AppManifest.model_validate({
        "id": "smoke", "name": "smoke", "command": ["smoke-server"],
        "public_url": "https://smoke.example.com", "host_port": 18100,
        "auth": {"client_id": "smoke", "discovery_url": "https://auth.example.com/discovery"},
        **changes,
    })


def test_authelia_refresh_lifetime_and_runtime(tmp_path, monkeypatch):
    original = '''identity_providers:
  oidc:
    hmac_secret: {{ secret "/config/secrets/hmac" }}
    authorization_policies:
      smartsearch_yuwk: {default_policy: two_factor}
    claims_policies:
      smartsearch_identity: {}
    clients:
      - client_id: untouched
        client_secret: {{ secret "/config/secrets/client" }}
        redirect_uris: [https://other.example.com/callback]
'''
    app = manifest()
    assert app.refresh_token_lifetime_days == 180
    candidate = authelia_text(original, app, {"OIDC_CLIENT_SECRET": "s" * 40})
    oidc = template_yaml(candidate)["identity_providers"]["oidc"]
    assert oidc["lifespans"]["custom"]["mcp_platform_smoke"]["refresh_token"] == "180d"
    assert oidc["clients"][1]["lifespan"] == "mcp_platform_smoke"
    assert '{{ secret "/config/secrets/hmac" }}' in candidate
    assert '{{ secret "/config/secrets/client" }}' in candidate
    assert authelia_text(candidate, app, {}) == candidate
    custom = authelia_text(candidate, manifest(refresh_token_lifetime_days=210), {})
    assert template_yaml(custom)["identity_providers"]["oidc"]["lifespans"]["custom"]["mcp_platform_smoke"]["refresh_token"] == "210d"
    assert authelia_text(custom, manifest(refresh_token_lifetime_days=210), {}) == custom
    for invalid in (0, -1, "180", True):
        with pytest.raises(ValueError):
            manifest(refresh_token_lifetime_days=invalid)
    import mcp_platform.auth as auth
    monkeypatch.setattr(auth, "PlatformOIDCProxy", lambda **kw: SimpleNamespace(**kw))
    config = RuntimeConfig(name="smoke", public_base_url=app.public_url,
        oidc_discovery_url=app.auth.discovery_url, oidc_client_id="smoke",
        oidc_client_secret="s" * 40, jwt_signing_key="j" * 40,
        storage_encryption_key="e" * 40, authorized_usernames={"writer"},
        storage_path=str(tmp_path / "oauth"))
    provider, _ = build_provider(config)
    assert provider.fallback_refresh_token_expiry_seconds == 180 * 86400
    assert app.runtime_environment["OAUTH_REFRESH_TOKEN_LIFETIME_DAYS"] == "180"


def test_mcphub_rollback_keeps_new_oauth_state(tmp_path):
    path = tmp_path / "hub.json"
    path.write_text(json.dumps({"systemConfig": {"oauthServer": {
        "refreshTokenLifetime": 1209600}}, "oauthTokens": ["original"]}))
    journal = Journal(tmp_path / "journal.json", {"files": []})
    keys = ["systemConfig", "oauthServer", "refreshTokenLifetime"]
    assert journal.replace_json_value(path, keys, 180 * 86400, expected_hash=digest(path))
    state = json.loads(path.read_text())
    state["oauthTokens"].append("new-after-deploy")
    path.write_text(json.dumps(state))
    journal.restore_json_values()
    restored = json.loads(path.read_text())
    assert restored["oauthTokens"] == ["original", "new-after-deploy"]
    assert restored["systemConfig"]["oauthServer"]["refreshTokenLifetime"] == 1209600
