#!/usr/bin/env python3
"""Collect compact host, network, proxy, Tailscale, and Hermes runtime facts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import sys
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


FACT_KEY = "host_environment"
SCHEMA_VERSION = 2
HERMES = os.environ.get(
    "HERMES_CLI",
    "/home/hermes/.hermes/hermes-agent/venv/bin/hermes",
)
HERMES_PROFILES = Path(
    os.environ.get("HERMES_PROFILES_DIR", "/home/hermes/.hermes/profiles")
)
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            result[key] = value.strip().strip('"')
    except OSError:
        pass
    return result


def _uptime_seconds(path: Path = Path("/proc/uptime")) -> int | None:
    try:
        return int(float(path.read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def _host_health() -> dict[str, Any]:
    health: dict[str, Any] = {}
    try:
        one, five, fifteen = os.getloadavg()
        health["load_average"] = {
            "one_minute": round(one, 2),
            "five_minutes": round(five, 2),
            "fifteen_minutes": round(fifteen, 2),
        }
    except OSError:
        pass

    try:
        meminfo: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0]) * 1024
        total = meminfo["MemTotal"]
        available = meminfo["MemAvailable"]
        health["memory"] = {
            "total_bytes": total,
            "available_bytes": available,
            "used_percent": round((total - available) * 100 / total, 1),
        }
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        pass

    try:
        disk = shutil.disk_usage("/")
        health["root_disk"] = {
            "total_bytes": disk.total,
            "free_bytes": disk.free,
            "used_percent": round(disk.used * 100 / disk.total, 1),
        }
    except (OSError, ZeroDivisionError):
        pass
    return health


def _network() -> dict[str, Any]:
    addresses: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    try:
        routes = [
            {
                key: route[key]
                for key in ("dst", "gateway", "dev", "prefsrc", "metric")
                if key in route
            }
            for route in run_json(["ip", "-j", "route", "show", "default"])
        ]
        default_interfaces = {
            route["dev"] for route in routes if route.get("dev")
        }
        for interface in run_json(["ip", "-j", "address", "show"]):
            ifname = interface.get("ifname", "")
            if (
                ifname == "lo"
                or ifname.startswith(("br-", "docker", "veth"))
                or (
                    ifname not in default_interfaces
                    and not ifname.startswith(("tailscale", "wg"))
                )
            ):
                continue
            for address in interface.get("addr_info") or []:
                if address.get("scope") != "global":
                    continue
                addresses.append(
                    {
                        "interface": ifname,
                        "family": address.get("family"),
                        "address": address.get("local"),
                        "prefixlen": address.get("prefixlen"),
                    }
                )
    except CollectorError:
        pass

    nameservers: list[str] = []
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[0] == "nameserver":
                nameservers.append(fields[1])
    except OSError:
        pass
    return {
        "addresses": addresses,
        "default_routes": routes,
        "dns_nameservers": nameservers,
    }


def _sanitize_proxy(value: str | None) -> dict[str, Any]:
    if not value:
        return {"configured": False}
    candidate = value if "://" in value else f"http://{value}"
    parsed = urlsplit(candidate)
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    endpoint = urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))
    return {"configured": True, "endpoint": endpoint}


def _proxy_environment() -> dict[str, Any]:
    def first(*names: str) -> str | None:
        return next((os.environ[name] for name in names if os.environ.get(name)), None)

    no_proxy = first("NO_PROXY", "no_proxy")
    return {
        "scope": "lingjun_cron_process",
        "http_proxy": _sanitize_proxy(first("HTTP_PROXY", "http_proxy")),
        "https_proxy": _sanitize_proxy(first("HTTPS_PROXY", "https_proxy")),
        "all_proxy": _sanitize_proxy(first("ALL_PROXY", "all_proxy")),
        "no_proxy": [entry.strip() for entry in (no_proxy or "").split(",") if entry.strip()],
    }


def _tailscale(network: dict[str, Any]) -> dict[str, Any]:
    interface_ips = [
        address["address"]
        for address in network.get("addresses", [])
        if str(address.get("interface", "")).startswith("tailscale")
    ]
    try:
        status = run_json(["tailscale", "status", "--json"], timeout=10)
    except CollectorError:
        return {
            "cli_available": False,
            "interface_present": bool(interface_ips),
            "self": {"tailscale_ips": interface_ips},
        }
    self_status = status.get("Self") or {}
    tailnet = status.get("CurrentTailnet") or {}
    return {
        "cli_available": True,
        "interface_present": bool(interface_ips),
        "backend_state": status.get("BackendState"),
        "tailnet": tailnet.get("Name"),
        "magic_dns_suffix": status.get("MagicDNSSuffix"),
        "self": {
            "dns_name": self_status.get("DNSName"),
            "tailscale_ips": self_status.get("TailscaleIPs") or [],
            "online": self_status.get("Online"),
        },
    }


def _telegram_config(profile: str) -> dict[str, Any]:
    try:
        import yaml

        data = yaml.safe_load(
            (HERMES_PROFILES / profile / "config.yaml").read_text(
                encoding="utf-8"
            )
        ) or {}
    except (ImportError, OSError, ValueError):
        return {"configured": False}
    platform = (data.get("platforms") or {}).get("telegram")
    configured = "telegram" in data or platform is not None
    result: dict[str, Any] = {"configured": configured}
    if isinstance(platform, dict) and isinstance(platform.get("enabled"), bool):
        result["enabled_override"] = platform["enabled"]
    return result


def _hermes_profiles() -> dict[str, Any]:
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    result = run([HERMES, "profile", "list"], timeout=20, env=env)
    if result.returncode != 0:
        return {"available": False, "profiles": []}

    profiles: list[dict[str, Any]] = []
    for raw_line in result.stdout.splitlines():
        line = ANSI_RE.sub("", raw_line).strip()
        active = line.startswith("◆")
        line = line.lstrip("◆ ").strip()
        columns = re.split(r"\s{2,}", line)
        if len(columns) < 3 or columns[0] in {"Profile", "───────────────"}:
            continue
        gateway = columns[2]
        if gateway not in {"running", "stopped"}:
            continue
        profiles.append(
            {
                "name": columns[0],
                "gateway": gateway,
                "active": active,
                "telegram": _telegram_config(columns[0]),
            }
        )
    return {"available": True, "profiles": profiles}


def collect_snapshot() -> dict[str, Any]:
    os_release = _os_release()
    network = _network()
    timezone = ""
    try:
        timezone = Path("/etc/timezone").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return {
        "schema_version": SCHEMA_VERSION,
        "observed_at": observed_at(),
        "scope": "linux_host_and_lingjun_cron",
        "host": {
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn(),
            "os": os_release.get("PRETTY_NAME") or platform.system(),
            "os_id": os_release.get("ID"),
            "kernel": platform.release(),
            "architecture": platform.machine(),
            "timezone": timezone,
            "uptime_seconds": _uptime_seconds(),
        },
        "health": _host_health(),
        "network": network,
        "tailscale": _tailscale(network),
        "proxy": _proxy_environment(),
        "hermes": _hermes_profiles(),
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
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            commit_snapshot(FACT_KEY, snapshot)
        return 0
    except CollectorError as exc:
        print(f"environment collector failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
