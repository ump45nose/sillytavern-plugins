"""仅验证已有服务入口失败时恢复网络配置，不触碰业务进程。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_platform.manifest import AppManifest, Target


def test_existing_failure_only_restores_network(tmp_path, monkeypatch):
    import mcp_platform.deploy as deployment
    import mcp_platform.exposure as module

    app = AppManifest(id="existing", name="existing", deployment_mode="existing",
                      authentication="oauth", public_url="https://existing.example.com", host_port=8000)
    source = tmp_path / "source"
    source.mkdir()
    (source / "mcp.app.yaml").write_text(app.model_dump_json())
    auth = tmp_path / "authelia.yml"
    auth.write_text("keep authentication and clients")
    tunnel = tmp_path / "tunnel.yml"
    original = "ingress:\n  - hostname: remote.example.com\n    service: http://127.0.0.1:8001\n  - service: http_status:404\n"
    tunnel.write_text(original)
    target = Target(runtime_root=str(tmp_path / "runtime"), tunnel_config=str(tunnel),
                    tunnel_compose="unused", tunnel_id="unused", authelia_config=str(auth),
                    cloudflare_env="unused")
    switches = []
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "probe_existing", lambda *a, **kw: None)
    monkeypatch.setattr(module, "validate_tunnel_candidate", lambda *a: None)
    monkeypatch.setattr(module, "switch_tunnel", lambda *a: switches.append("apply"))
    monkeypatch.setattr(deployment, "switch_tunnel", lambda *a: switches.append("restore"))

    def forbid(*a, **kw):
        raise AssertionError("入口模式不得控制业务或 Authelia")

    monkeypatch.setattr(module, "run", forbid)
    monkeypatch.setattr(deployment, "run", forbid)
    monkeypatch.setattr(deployment, "restart_authelia", forbid)

    class FakeCloudflare:
        client = SimpleNamespace(close=lambda: None)
        def __init__(self, target): pass
        def find_zone(self, hostname): pass
        def records(self, hostname): return []
        def switch(self, *args): raise RuntimeError("simulated DNS failure")

    monkeypatch.setattr(module, "Cloudflare", FakeCloudflare)
    with pytest.raises(RuntimeError, match="已恢复本次变更"):
        module.deploy_existing(app, source, target)
    assert tunnel.read_text() == original
    assert auth.read_text() == "keep authentication and clients"
    assert switches == ["apply", "restore"]
    journal = json.loads(next(Path(target.runtime_root).rglob("journal.json")).read_text())
    assert journal["rollback_status"] == "complete"
    assert journal.get("service_attempted") is None
