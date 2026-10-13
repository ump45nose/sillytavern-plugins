"""首版关键路径冒烟；不扩大到业务回归。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp import Client
from fastmcp.server.auth import AccessToken
from starlette.testclient import TestClient

from mcp_platform import RuntimeConfig, authorize, create_http_app, create_server
from mcp_platform.auth import build_provider
from mcp_platform.cli import init_project
from mcp_platform.infra import Journal, ddns_text, tunnel_text
from mcp_platform.manifest import load_app


def production(**kwargs):
    return RuntimeConfig(name="smoke", public_base_url="https://smoke.example.com",
        oidc_discovery_url="https://auth.example.com/.well-known/openid-configuration",
        oidc_client_id="smoke", oidc_client_secret="s" * 40,
        jwt_signing_key="j" * 40, storage_encryption_key="e" * 40,
        authorized_usernames={"writer", "reader"}, read_only_usernames={"reader"}, **kwargs)


@pytest.mark.asyncio
async def test_local_http_and_policy(tmp_path):
    cfg = RuntimeConfig(name="smoke", development_no_auth=True, allowed_hosts=["testserver"])
    server = create_server(cfg, healthcheck=lambda: {"status": "ok"})

    @server.tool
    def hello() -> dict:
        return {"ok": True}

    async with Client(server) as client:
        assert (await client.call_tool("hello", {})).data == {"ok": True}
    with TestClient(create_http_app(server, cfg)) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
    with pytest.raises(ValueError):
        RuntimeConfig(name="bad", development_no_auth=True, host="0.0.0.0")
    with pytest.raises(ValueError):
        RuntimeConfig(name="bad")
    policy = production()
    for user, write in (("writer", True), ("reader", False), ("stranger", False)):
        token = AccessToken(token="test", client_id="test", scopes=["openid"],
                            claims={"upstream_claims": {"preferred_username": user}})
        context = SimpleNamespace(token=token)
        assert authorize("read", policy)(context) == (user != "stranger")
        assert authorize("write", policy)(context) == write
        assert authorize("execute", policy)(context) is False


@pytest.mark.asyncio
async def test_encrypted_state_survives_restart(tmp_path, monkeypatch):
    import mcp_platform.auth as module
    monkeypatch.setattr(module, "PlatformOIDCProxy", lambda **kw: SimpleNamespace(**kw))
    for backend in ("filetree", "disk"):
        cfg = production(storage_path=str(tmp_path / backend), storage_backend=backend,
                         storage_salt="existing-service-oauth-v1")
        first, raw = build_provider(cfg)
        key = "https://chatgpt.com/oauth/client.json"
        await first.client_storage.put(key, {"registered": True}, collection="clients")
        close = getattr(raw, "close", None)
        if close:
            await close()
        second, raw = build_provider(cfg)
        assert await second.client_storage.get(key, collection="clients") == {"registered": True}
        assert not any(b'"registered"' in p.read_bytes() for p in (tmp_path / backend).rglob("*") if p.is_file())
        if getattr(raw, "close", None):
            await raw.close()


def test_init_and_infra_restore(tmp_path):
    project = tmp_path / "new-mcp"
    init_project("new-mcp", project)
    app = load_app(project)
    old = "tunnel: test\ningress:\n  - hostname: existing.example.com\n    service: http://127.0.0.1:8001\n  - service: http_status:404\n"
    candidate = tunnel_text(old, app)
    assert "existing.example.com" in candidate
    assert tunnel_text(candidate, app) == candidate
    ddns = "dnsconf:\n  - ipv4:\n      domains: ['new-mcp.example.com?proxied=true', auth.example.com]\n"
    assert "auth.example.com" in ddns_text(ddns, app.hostname)
    assert app.hostname not in ddns_text(ddns, app.hostname)
    shared = tmp_path / "shared.yaml"
    shared.write_text(old)
    journal = Journal(tmp_path / "journal.json", {"files": []})
    journal.replace_file(shared, candidate)
    assert journal.restore_files() == [str(shared)]
    assert shared.read_text() == old
    import hashlib
    expected = hashlib.sha256(old.encode()).hexdigest()
    shared.write_text(old + "# external change\n")
    with pytest.raises(RuntimeError, match="外部修改"):
        journal.replace_file(shared, candidate, expected_hash=expected)
    assert shared.read_text() == old + "# external change\n"
    shared.write_text(old)
    journal.replace_file(shared, candidate)
    shared.write_text(candidate + "# external change\n")
    with pytest.raises(RuntimeError, match="外部修改"):
        journal.restore_files()


def test_failed_deploy_rolls_back(tmp_path, monkeypatch):
    import os
    import pwd

    import mcp_platform.deploy as module
    from mcp_platform.manifest import Target

    project = tmp_path / "isolated"
    init_project("isolated", project)
    app = load_app(project)
    authelia = tmp_path / "auth.yml"
    authelia.write_text("original")
    tunnel = tmp_path / "tunnel.yml"
    tunnel.write_text("original")
    target = Target(runtime_root=str(tmp_path / "runtime"), build_user=pwd.getpwuid(os.getuid()).pw_name,
        source_roots={app.id: str(project)}, tunnel_config=str(tunnel), tunnel_compose="unused",
        tunnel_id="unused", authelia_config=str(authelia), cloudflare_env="unused")
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "chown", lambda *a: None)
    monkeypatch.setattr(module, "prepare_env", lambda *a: (tmp_path / "env", {}))
    monkeypatch.setattr(module, "authelia_text", lambda *a: "candidate-auth")
    monkeypatch.setattr(module, "tunnel_text", lambda *a: "candidate-tunnel")
    monkeypatch.setattr(module, "validate_authelia_candidate", lambda *a: None)
    monkeypatch.setattr(module, "validate_tunnel_candidate", lambda *a: None)
    monkeypatch.setattr(module, "container_for", lambda *a: None)
    monkeypatch.setattr(module, "build_bundle", lambda *a: ("test:image", "commit", "core"))
    monkeypatch.setattr(module, "run", lambda *a, **kw: "commit")
    monkeypatch.setattr(module, "restart_authelia", lambda *a: None)
    monkeypatch.setattr(module, "switch_tunnel", lambda *a: None)
    monkeypatch.setattr(module, "wait_health", lambda *a, **kw: None)

    class FakeCloudflare:
        client = SimpleNamespace(close=lambda: None)
        def __init__(self, target): pass
        def find_zone(self, hostname): pass
        def records(self, hostname): return []
        def switch(self, *args): raise RuntimeError("simulated DNS failure")

    monkeypatch.setattr(module, "Cloudflare", FakeCloudflare)
    with pytest.raises(RuntimeError, match="已回滚"):
        module.deploy(app, project, target)
    assert authelia.read_text() == tunnel.read_text() == "original"
    record = next(Path(target.runtime_root).rglob("journal.json"))
    assert json.loads(record.read_text())["rollback_status"] == "complete"
