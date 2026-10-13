#!/usr/bin/env python3
"""Collect a compact, secret-free Docker inventory for agent orientation."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any

try:
    from .shared_state_collector import (
        CollectorError,
        commit_snapshot,
        observed_at,
        run,
        run_json,
    )
except ImportError:
    from shared_state_collector import (
        CollectorError,
        commit_snapshot,
        observed_at,
        run,
        run_json,
    )


FACT_KEY = "container_inventory"
SUMMARY_FACT_KEY = "container_summary"
SCHEMA_VERSION = 1


def _published_ports(raw_ports: dict[str, Any] | None) -> list[dict[str, str]]:
    ports: list[dict[str, str]] = []
    for container_port, bindings in sorted((raw_ports or {}).items()):
        for binding in bindings or []:
            ports.append(
                {
                    "container": container_port,
                    "host_ip": binding.get("HostIp", ""),
                    "host_port": binding.get("HostPort", ""),
                }
            )
    return ports


def _container_summary(item: dict[str, Any]) -> dict[str, Any]:
    config = item.get("Config") or {}
    state = item.get("State") or {}
    host_config = item.get("HostConfig") or {}
    network_settings = item.get("NetworkSettings") or {}
    labels = config.get("Labels") or {}
    health = state.get("Health") or {}
    return {
        "name": str(item.get("Name", "")).lstrip("/"),
        "image": config.get("Image") or item.get("Image", ""),
        "state": state.get("Status", "unknown"),
        "health": health.get("Status"),
        "status": state.get("Error") or "",
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "network_mode": host_config.get("NetworkMode"),
        "networks": sorted((network_settings.get("Networks") or {}).keys()),
        "published_ports": _published_ports(network_settings.get("Ports")),
        "restart_policy": (host_config.get("RestartPolicy") or {}).get("Name", ""),
        "privileged": bool(host_config.get("Privileged", False)),
    }


def collect_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed_at(),
        "scope": "linux_host_docker",
        "host": socket.gethostname(),
        "engine": {"name": "docker", "available": False},
        "summary": {
            "total": 0,
            "running": 0,
            "stopped": 0,
            "unhealthy": 0,
        },
        "containers": [],
    }

    version = run(["docker", "version", "--format", "{{.Server.Version}}"])
    if version.returncode != 0:
        snapshot["engine"]["reason"] = "docker daemon unavailable"
        return snapshot

    snapshot["engine"] = {
        "name": "docker",
        "available": True,
        "server_version": version.stdout.strip(),
    }
    ids_result = run(["docker", "ps", "-aq"])
    if ids_result.returncode != 0:
        raise CollectorError("docker ps failed")
    container_ids = [line for line in ids_result.stdout.splitlines() if line]
    if not container_ids:
        return snapshot

    inspected = run_json(["docker", "inspect", *container_ids], timeout=45)
    containers = sorted(
        (_container_summary(item) for item in inspected),
        key=lambda item: item["name"].lower(),
    )
    running = sum(item["state"] == "running" for item in containers)
    unhealthy = sum(item["health"] == "unhealthy" for item in containers)
    snapshot["containers"] = containers
    snapshot["summary"] = {
        "total": len(containers),
        "running": running,
        "stopped": len(containers) - running,
        "unhealthy": unhealthy,
    }
    return snapshot


def compact_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    projects: dict[str, dict[str, Any]] = {}
    attention: list[dict[str, Any]] = []
    for container in snapshot.get("containers", []):
        project_name = container.get("compose_project") or "standalone"
        project = projects.setdefault(
            project_name,
            {
                "name": project_name,
                "services": [],
                "running": 0,
                "stopped": 0,
                "unhealthy": 0,
            },
        )
        project["services"].append(
            container.get("compose_service") or container["name"]
        )
        if container["state"] == "running":
            project["running"] += 1
        else:
            project["stopped"] += 1
        if container.get("health") == "unhealthy":
            project["unhealthy"] += 1
        if container["state"] != "running" or container.get("health") == "unhealthy":
            attention.append(
                {
                    "name": container["name"],
                    "image": container["image"],
                    "state": container["state"],
                    "health": container.get("health"),
                    "compose_project": container.get("compose_project"),
                }
            )
    for project in projects.values():
        project["services"].sort(key=str.lower)
    return {
        "schema_version": snapshot["schema_version"],
        "observed_at": snapshot["observed_at"],
        "scope": snapshot["scope"],
        "host": snapshot["host"],
        "engine": snapshot["engine"],
        "summary": snapshot["summary"],
        "projects": sorted(projects.values(), key=lambda item: item["name"].lower()),
        "attention": sorted(attention, key=lambda item: item["name"].lower()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the sanitized snapshot instead of committing it",
    )
    args = parser.parse_args()
    try:
        snapshot = collect_snapshot()
        if args.stdout:
            print(
                json.dumps(
                    {
                        "summary": compact_summary(snapshot),
                        "inventory": snapshot,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            commit_snapshot(SUMMARY_FACT_KEY, compact_summary(snapshot))
            commit_snapshot(FACT_KEY, snapshot)
        return 0
    except CollectorError as exc:
        print(f"container collector failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
