import pytest
import yaml
from pydantic import ValidationError

from mcp_platform.deploy import compose_text
from mcp_platform.manifest import AppManifest, BindMount


def test_existing_named_volume_and_read_only_sources_are_preserved():
    app = AppManifest.model_validate({
        "id": "usage-monitor-mcp", "name": "Usage", "deployment_mode": "existing",
        "public_url": "https://usage.invalid", "host_port": 18103,
        "volumes": [{"name": "usage-data", "mount": "/data"}],
        "bind_mounts": [{"source": "/srv/token-data", "mount": "/sources/token"}],
    })
    result = yaml.safe_load(compose_text(app, "local/usage:test", "/private/service.env"))
    assert result["services"]["app"]["volumes"] == [
        "usage-data:/data",
        {"type": "bind", "source": "/srv/token-data", "target": "/sources/token", "read_only": True},
    ]
    assert result["volumes"] == {"usage-data": {"name": "usage-data"}}


@pytest.mark.parametrize("source,mount,read_only", [
    ("relative", "/sources/token", True),
    ("/srv/token", "relative", True),
    ("/", "/sources/token", True),
    ("/srv/../etc", "/sources/token", True),
    ("/srv/token", "/sources/token", False),
])
def test_unsafe_or_writable_bind_is_rejected(source, mount, read_only):
    with pytest.raises(ValidationError):
        BindMount(source=source, mount=mount, read_only=read_only)
