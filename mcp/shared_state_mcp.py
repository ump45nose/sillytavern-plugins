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
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP


_parser = argparse.ArgumentParser()
_parser.add_argument("--profile", required=True, help="Hermes profile name")
_parser.add_argument("--db", default=None, help="Shared SQLite path (override)")
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
}
WRITE_PERMS: dict[str, set[str]] = {
    "lingjun": {"tasks", "shared"},
    "companion": {"social", "shared"},
    "ops": {"infra", "homeassistant", "media", "shared"},
    "research": {"research", "shared"},
    "xp": {"xp"},
}


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
        """
    )
    return conn


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


mcp = FastMCP("shared-state")


@mcp.tool()
def commit_fact(domain: str, key: str, value: str) -> str:
    """Store an authoritative environment fact with audit history."""
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _write_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot write domain '{domain}'"
    parsed, error = _structured(value)
    if error:
        return error
    stored = json.dumps(parsed, ensure_ascii=False)
    timestamp = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO facts(domain,key,value,source_profile,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(domain,key) DO UPDATE SET "
            "value=excluded.value, source_profile=excluded.source_profile, "
            "updated_at=excluded.updated_at",
            (domain, key, stored, PROFILE, timestamp),
        )
        conn.execute(
            "INSERT INTO fact_history(domain,key,value,source_profile,ts) "
            "VALUES(?,?,?,?,?)",
            (domain, key, stored, PROFILE, timestamp),
        )
    return f"OK commit_fact {domain}/{key}"


@mcp.tool()
def get_context(domain: str, query: str = "") -> str:
    """Read facts in a domain, optionally filtering keys by substring."""
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


@mcp.tool()
def get_resource(domain: str, id: str) -> str:
    """Read one environment fact by its exact key."""
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


@mcp.tool()
def record_observation(domain: str, observation: str) -> str:
    """Append a structured observation and matching event."""
    if domain not in VALID_DOMAINS:
        return f"ERROR: unknown domain '{domain}'"
    if not _write_ok(domain):
        return f"DENIED: profile '{PROFILE}' cannot write domain '{domain}'"
    parsed, error = _structured(observation)
    if error:
        return error
    stored = json.dumps(parsed, ensure_ascii=False)
    timestamp = time.time()
    with _db() as conn:
        conn.execute(
            "INSERT INTO observations(domain,payload,source_profile,ts) "
            "VALUES(?,?,?,?)",
            (domain, stored, PROFILE, timestamp),
        )
        conn.execute(
            "INSERT INTO events(domain,etype,payload,source_profile,ts) "
            "VALUES(?,?,?,?,?)",
            (domain, "observation", stored, PROFILE, timestamp),
        )
    return f"OK record_observation {domain}"


@mcp.tool()
def list_events(domain: str, since: float = 0.0) -> str:
    """Read the event stream for a domain after a Unix timestamp."""
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
    mcp.run()
