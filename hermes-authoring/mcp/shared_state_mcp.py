#!/usr/bin/env python3
"""Hermes cross-profile environment layer for deterministic shared facts.

One stdio MCP server is launched per Hermes profile with ``--profile``.  It
enforces a domain permission matrix on every read and write.  Preferences,
emotions, and inference belong in profile-private memory, not here.

Contract tools:
  get_context(domain, query)
  get_resource(domain, id)
  record_observation(domain, observation)
  commit_fact(domain, key, value)
  list_events(domain, since)

The default SQLite path is resolved relative to the deployed script
(``../shared_state.db``), never from ``HERMES_HOME``.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


_parser = argparse.ArgumentParser()
_parser.add_argument("--profile", required=True, help="Hermes profile name")
_parser.add_argument("--db", default=None, help="Shared SQLite path (override)")
_parser.add_argument(
    "--commit-domain",
    default=None,
    help="Trusted collector mode: commit stdin JSON to this domain",
)
_parser.add_argument(
    "--commit-key",
    default=None,
    help="Trusted collector mode: commit stdin JSON under this key",
)
_args, _ = _parser.parse_known_args()
PROFILE = _args.profile

DB_PATH = (
    _args.db
    or os.environ.get("HERMES_SHARED_STATE_DB")
    or str(Path(__file__).resolve().parent.parent / "shared_state.db")
)

ALL = "*"
VALID_DOMAINS = {
    "infra",
    "homeassistant",
    "media",
    "research",
    "xp",
    "social",
    "tasks",
    "shared",
}
READ_PERMS: dict[str, object] = {
    "lingjun": ALL,
    "companion": {"social", "shared", "xp"},
    "ops": {"infra", "homeassistant", "media", "shared"},
    "research": {"research", "shared"},
    "xp": {"xp"},
    "codex": ALL,
}
WRITE_PERMS: dict[str, set[str]] = {
    "lingjun": {"tasks", "shared"},
    "companion": {"social", "shared"},
    "ops": {"infra", "homeassistant", "media", "shared"},
    "research": {"research", "shared"},
    "xp": {"xp"},
    "codex": {"infra"},
}
CODEX_RESERVED_INFRA_KEYS = {
    "host_environment",
    "container_summary",
    "container_inventory",
    "host",
    "containers",
}
AUDIT_RETENTION_SECONDS = 180 * 24 * 60 * 60
MAX_FACT_VERSIONS_PER_KEY = 1000


def _can(perms: dict, domain: str) -> bool:
    allowed = perms.get(PROFILE, set())
    return allowed == ALL or domain in allowed


def _read_ok(domain: str) -> bool:
    return _can(READ_PERMS, domain)


def _write_ok(domain: str) -> bool:
    return _can(WRITE_PERMS, domain)


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS shared_state (
            domain TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            updated_by TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY (domain, key)
        );
        CREATE TABLE IF NOT EXISTS facts (
            domain TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            source_profile TEXT NOT NULL, updated_at REAL NOT NULL,
            PRIMARY KEY (domain, key)
        );
        CREATE TABLE IF NOT EXISTS fact_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
            source_profile TEXT NOT NULL, ts REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL, payload TEXT NOT NULL,
            source_profile TEXT NOT NULL, ts REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL, etype TEXT NOT NULL, payload TEXT NOT NULL,
            source_profile TEXT NOT NULL, ts REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_events_domain_ts ON events(domain, ts);
        CREATE INDEX IF NOT EXISTS ix_obs_domain_ts ON observations(domain, ts);
        CREATE INDEX IF NOT EXISTS ix_fact_history_key_ts
            ON fact_history(domain, key, ts DESC);
        """
    )
    return conn


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _prune_audit(conn: sqlite3.Connection, timestamp: float) -> None:
    cutoff = timestamp - AUDIT_RETENTION_SECONDS
    conn.execute("DELETE FROM fact_history WHERE ts < ?", (cutoff,))
    conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))
    # ``observations`` is a legacy compatibility table. New observations are
    # written only to ``events``; bound the old rows while readers migrate.
    conn.execute("DELETE FROM observations WHERE ts < ?", (cutoff,))


def _prune_fact_versions(
    conn: sqlite3.Connection, domain: str, key: str
) -> None:
    conn.execute(
        "DELETE FROM fact_history WHERE id IN ("
        "SELECT id FROM fact_history WHERE domain=? AND key=? "
        "ORDER BY ts DESC, id DESC LIMIT -1 OFFSET ?"
        ")",
        (domain, key, MAX_FACT_VERSIONS_PER_KEY),
    )


def _structured(value):
    """Coerce a value to structured JSON and reject free-text prose."""
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value, None
    if isinstance(value, str):
        candidate = value.strip()
        try:
            return json.loads(candidate), None
        except Exception:
            if (
                len(candidate) <= 64
                and "\n" not in candidate
                and " " not in candidate
            ):
                return candidate, None
            return None, (
                "REJECTED: the environment layer stores STRUCTURED facts, not "
                "free text. Pass JSON (object/array/scalar). Preferences, "
                "emotions and inference belong in profile-private memory."
            )
    return None, "REJECTED: unsupported value type"


SERVER_INSTRUCTIONS = """\
Authoritative runtime context for this local Hermes environment. Before
diagnosing or changing local networking, DNS/proxies, ports, Docker/containers,
shared infrastructure, Hermes profiles, gateways/Telegram, Home Assistant, or
media services, use the smallest relevant baseline: infra/host_environment for
host, network, proxy, or Hermes/gateway questions; infra/container_summary for
Docker or shared-service questions. Read infra/container_inventory only when
exact container, port, or network details are needed. Check updated_at:
observations can become stale and are evidence, not permission to mutate. Never
request or store credentials. Codex may write only directly verified,
structured infra facts and observations. Collector-owned baseline keys are
ops-only. After commit_fact, read the exact resource back and verify it.
"""

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)

mcp = FastMCP("shared-state", instructions=SERVER_INSTRUCTIONS)


@mcp.tool(annotations=WRITE_ANNOTATIONS)
def commit_fact(domain: str, key: str, value: str) -> str:
    """Store a verified structured fact with audit history.

    Use only after direct observation or a deterministic collector result.
    Never store credentials, preferences, inference, or unverified prose.
    """
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _write_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot write domain '{domain}'"
    if (
        PROFILE == "codex"
        and domain == "infra"
        and key in CODEX_RESERVED_INFRA_KEYS
    ):
        return (
            f"DENIED: profile 'codex' cannot overwrite collector-owned "
            f"fact '{domain}/{key}'"
        )
    parsed, error = _structured(value)
    if error:
        return error
    stored = _canonical_json(parsed)
    timestamp = time.time()
    with _db() as conn:
        previous = conn.execute(
            "SELECT value FROM facts WHERE domain=? AND key=?",
            (domain, key),
        ).fetchone()
        changed = previous is None or previous[0] != stored
        conn.execute(
            "INSERT INTO facts(domain,key,value,source_profile,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(domain,key) DO UPDATE SET "
            "value=excluded.value, source_profile=excluded.source_profile, "
            "updated_at=excluded.updated_at",
            (domain, key, stored, PROFILE, timestamp),
        )
        if changed:
            conn.execute(
                "INSERT INTO fact_history(domain,key,value,source_profile,ts) "
                "VALUES(?,?,?,?,?)",
                (domain, key, stored, PROFILE, timestamp),
            )
            conn.execute(
                "INSERT INTO events(domain,etype,payload,source_profile,ts) "
                "VALUES(?,?,?,?,?)",
                (
                    domain,
                    "fact_changed",
                    _canonical_json({"key": key, "value": parsed}),
                    PROFILE,
                    timestamp,
                ),
            )
        _prune_fact_versions(conn, domain, key)
        _prune_audit(conn, timestamp)
    return f"OK commit_fact {domain}/{key}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
def get_context(domain: str, query: str = "") -> str:
    """Read runtime facts in a domain, optionally filtering keys by substring.

    Use before local infrastructure diagnosis or changes when several related
    facts may matter. For the basic host and container baseline, prefer exact
    get_resource calls for infra/host_environment and infra/container_summary.
    Fetch infra/container_inventory only for exact container details.
    """
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _read_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot read domain '{domain}'"
    with _db() as conn:
        rows = conn.execute(
            "SELECT key,value,source_profile,updated_at FROM facts "
            "WHERE domain=? ORDER BY key",
            (domain,),
        ).fetchall()
    query_lower = query.lower().strip()
    result = [
        {
            "key": key,
            "value": json.loads(value),
            "source_profile": source_profile,
            "updated_at": updated_at,
        }
        for (key, value, source_profile, updated_at) in rows
        if not query_lower or query_lower in key.lower()
    ]
    return (
        json.dumps(result, ensure_ascii=False)
        if result
        else f"(no facts in {domain})"
    )


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
def get_resource(domain: str, id: str) -> str:
    """Read one runtime fact by exact domain and key.

    Proactively call infra/host_environment for host, network, proxy, Hermes,
    or Telegram/gateway work, and infra/container_summary for basic Docker or
    shared-service orientation. Fetch infra/container_inventory only when exact
    container, port, network, or image details are needed. Check updated_at
    before relying on the value.
    """
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _read_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot read domain '{domain}'"
    with _db() as conn:
        row = conn.execute(
            "SELECT value,source_profile,updated_at FROM facts "
            "WHERE domain=? AND key=?",
            (domain, id),
        ).fetchone()
    if not row:
        return f"(empty: {domain}/{id} not set)"
    return json.dumps(
        {
            "value": json.loads(row[0]),
            "source_profile": row[1],
            "updated_at": row[2],
        },
        ensure_ascii=False,
    )


@mcp.tool(annotations=WRITE_ANNOTATIONS)
def record_observation(domain: str, observation: str) -> str:
    """Append a verified structured observation event.

    Use for point-in-time execution results, not credentials or inference.
    """
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _write_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot write domain '{domain}'"
    parsed, error = _structured(observation)
    if error:
        return error
    stored = _canonical_json(parsed)
    timestamp = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO events(domain,etype,payload,source_profile,ts) "
            "VALUES(?,?,?,?,?)",
            (domain, "observation", stored, PROFILE, timestamp),
        )
        _prune_audit(conn, timestamp)
    return f"OK record_observation {domain}"


@mcp.tool(annotations=READ_ONLY_ANNOTATIONS)
def list_events(domain: str, since: float = 0.0) -> str:
    """Read verified runtime events in a domain after a Unix timestamp.

    Use when recent changes, restarts, or observations may explain a current
    infrastructure symptom.
    """
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _read_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot read domain '{domain}'"
    with _db() as conn:
        rows = conn.execute(
            "SELECT etype,payload,source_profile,ts FROM events "
            "WHERE domain=? AND ts>? ORDER BY ts",
            (domain, float(since)),
        ).fetchall()
    result = [
        {
            "etype": event_type,
            "payload": json.loads(payload),
            "source_profile": source_profile,
            "ts": timestamp,
        }
        for (event_type, payload, source_profile, timestamp) in rows
    ]
    return (
        json.dumps(result, ensure_ascii=False)
        if result
        else f"(no events in {domain} since {since})"
    )


# Kanban intentionally stays out of shared-state.  The controller uses the
# native orchestrator surface and dispatcher workers use native lifecycle
# tools scoped by HERMES_KANBAN_TASK.


if __name__ == "__main__":
    if bool(_args.commit_domain) != bool(_args.commit_key):
        _parser.error("--commit-domain and --commit-key must be provided together")
    if _args.commit_domain:
        result = commit_fact(
            _args.commit_domain,
            _args.commit_key,
            sys.stdin.read(),
        )
        print(result)
        raise SystemExit(0 if result.startswith("OK ") else 1)
    mcp.run()
