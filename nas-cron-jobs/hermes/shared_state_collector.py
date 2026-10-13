"""Shared helpers for deterministic, secret-free shared-state collectors."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SHARED_STATE_SERVER = Path(
    os.environ.get(
        "HERMES_SHARED_STATE_SERVER",
        "/home/hermes/.hermes/mcp-servers/shared_state_mcp.py",
    )
)


class CollectorError(RuntimeError):
    """Raised when a collector cannot gather or commit its snapshot."""


def observed_at() -> str:
    """Return a UTC timestamp with second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def run(
    args: list[str],
    *,
    timeout: int = 15,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a bounded read-only command and capture text output."""
    try:
        return subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectorError(f"command unavailable: {args[0]}") from exc


def run_json(args: list[str], *, timeout: int = 15) -> Any:
    """Run a command and decode its JSON output."""
    result = run(args, timeout=timeout)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        raise CollectorError(f"{args[0]} failed: {message[:160]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CollectorError(f"{args[0]} returned invalid JSON") from exc


def commit_snapshot(
    key: str,
    payload: dict[str, Any],
    *,
    domain: str = "infra",
    profile: str = "ops",
    server: Path = DEFAULT_SHARED_STATE_SERVER,
) -> None:
    """Commit a collector snapshot through the shared-state ACL contract."""
    result = subprocess.run(
        [
            sys.executable,
            str(server),
            "--profile",
            profile,
            "--commit-domain",
            domain,
            "--commit-key",
            key,
        ],
        input=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.startswith("OK "):
        detail = (result.stderr or result.stdout).strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        raise CollectorError(f"shared-state commit failed: {message[:200]}")
