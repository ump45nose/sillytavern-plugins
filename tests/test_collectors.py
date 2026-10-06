"""Behavior tests for compact shared-state collectors."""

from __future__ import annotations

import subprocess

from collectors import collect_containers, collect_environment


def test_container_summary_keeps_orientation_fields_and_drops_secrets():
    raw = {
        "Name": "/database",
        "Config": {
            "Image": "postgres:17",
            "Env": ["PASSWORD=secret"],
            "Labels": {
                "com.docker.compose.project": "shared-data",
                "com.docker.compose.service": "postgres",
                "private": "secret",
            },
        },
        "State": {
            "Status": "running",
            "Health": {"Status": "healthy", "Log": [{"Output": "secret"}]},
        },
        "HostConfig": {
            "NetworkMode": "shared-data_default",
            "RestartPolicy": {"Name": "unless-stopped"},
            "Privileged": False,
        },
        "NetworkSettings": {
            "Networks": {"shared-data_default": {}},
            "Ports": {
                "5432/tcp": [{"HostIp": "127.0.0.1", "HostPort": "5432"}]
            },
        },
        "Mounts": [{"Source": "/secret/path", "Destination": "/var/lib/postgresql"}],
    }

    summary = collect_containers._container_summary(raw)

    assert summary["name"] == "database"
    assert summary["compose_project"] == "shared-data"
    assert summary["health"] == "healthy"
    assert summary["published_ports"] == [
        {
            "container": "5432/tcp",
            "host_ip": "127.0.0.1",
            "host_port": "5432",
        }
    ]
    serialized = repr(summary)
    assert "PASSWORD" not in serialized
    assert "/secret/path" not in serialized
    assert "Health" not in serialized


def test_compact_container_summary_groups_projects_and_flags_attention():
    snapshot = {
        "schema_version": 1,
        "observed_at": "2026-07-25T00:00:00+00:00",
        "scope": "linux_host_docker",
        "host": "test-host",
        "engine": {"name": "docker", "available": True},
        "summary": {"total": 2, "running": 1, "stopped": 1, "unhealthy": 1},
        "containers": [
            {
                "name": "redis",
                "image": "redis:alpine",
                "state": "running",
                "health": None,
                "compose_project": "database",
                "compose_service": "redis",
            },
            {
                "name": "uptime-kuma",
                "image": "uptime-kuma:1",
                "state": "exited",
                "health": "unhealthy",
                "compose_project": "monitor",
                "compose_service": "uptime-kuma",
            },
        ],
    }
    summary = collect_containers.compact_summary(snapshot)
    assert summary["projects"][0]["services"] == ["redis"]
    assert summary["attention"] == [
        {
            "name": "uptime-kuma",
            "image": "uptime-kuma:1",
            "state": "exited",
            "health": "unhealthy",
            "compose_project": "monitor",
        }
    ]


def test_proxy_sanitizer_removes_credentials_and_query():
    result = collect_environment._sanitize_proxy(
        "http://user:password@proxy.internal:7890/path?token=secret"
    )
    assert result == {
        "configured": True,
        "endpoint": "http://proxy.internal:7890/path",
    }


def test_hermes_profile_parser_extracts_gateway_state(monkeypatch):
    output = """
 Profile          Model                        Gateway      Alias
 ───────────────    ───────────────────────────    ───────────
  default         model-a                      stopped      —
 ◆lingjun         model-b                      running      lingjun
  ops             model-b                      stopped      —
"""

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, output, "")

    monkeypatch.setattr(collect_environment, "run", fake_run)
    monkeypatch.setattr(
        collect_environment,
        "_telegram_config",
        lambda profile: {"configured": profile == "lingjun"},
    )
    result = collect_environment._hermes_profiles()

    assert result == {
        "available": True,
        "profiles": [
            {
                "name": "default",
                "gateway": "stopped",
                "active": False,
                "telegram": {"configured": False},
            },
            {
                "name": "lingjun",
                "gateway": "running",
                "active": True,
                "telegram": {"configured": True},
            },
            {
                "name": "ops",
                "gateway": "stopped",
                "active": False,
                "telegram": {"configured": False},
            },
        ],
    }
