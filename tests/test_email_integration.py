"""仅检查本次容器配置、插件产物及邮件权限分流。"""

import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import yaml

from mcp_platform.cli import package_app
from mcp_platform.deploy import compose_text
from mcp_platform.manifest import load_app


def test_email_manifest_compose_and_package(tmp_path):
    source = Path(__file__).parents[1] / "integrations/email-mcp"
    app = load_app(source)
    compose = yaml.safe_load(compose_text(app, "local/email:test", "/private/service.env",
                                         "services:\n  other:\n    image: keep:1\n"))
    assert compose["services"]["other"] == {"image": "keep:1"}
    service = compose["services"]["email-mcp"]
    assert service["user"] == "1000:1001"
    assert service["working_dir"] == "/data" and service["init"] is True
    assert service["ports"] == ["127.0.0.1:9557:9557"]
    assert compose["networks"] == {"tool_net": {"external": True}}
    package_app(app, source, tmp_path / "plugin.zip")
    with zipfile.ZipFile(tmp_path / "plugin.zip") as archive:
        connection = json.loads(archive.read("mcp.json"))
        assert connection["mcpServers"]["email-mcp"]["url"] == app.public_url + "/mcp"
        assert app.plugin.logo in archive.namelist()


def test_email_permission():
    sys.path.insert(0, str(Path(__file__).parents[1] / "integrations/email-mcp/src"))
    from email_mcp_platform.server import email_permission
    from mcp_platform import RuntimeConfig

    cfg = RuntimeConfig.model_construct(development_no_auth=False,
        authorized_usernames={"owner", "reader"}, read_only_usernames={"reader"})
    check = email_permission(cfg)
    for username, readonly, expected in [
        ("owner", None, True), ("reader", True, True),
        ("reader", False, False), ("reader", None, False), ("stranger", True, False),
    ]:
        annotations = None if readonly is None else SimpleNamespace(readOnlyHint=readonly)
        ctx = SimpleNamespace(token=SimpleNamespace(claims={"preferred_username": username}),
                              component=SimpleNamespace(annotations=annotations))
        assert check(ctx) is expected
