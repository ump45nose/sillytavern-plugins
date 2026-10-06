"""Behavior tests for the local shared-state MCP contract."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


SOURCE = (
    Path(__file__).resolve().parents[1] / "mcp" / "shared_state_mcp.py"
)
CONTRACT_TOOLS = {
    "commit_fact",
    "get_context",
    "get_resource",
    "record_observation",
    "list_events",
}


@pytest.fixture
def shared_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", [str(SOURCE), "--profile", "lingjun", "--db", str(tmp_path / "state.db")]
    )
    spec = importlib.util.spec_from_file_location("shared_state_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_contract_has_no_kanban_shims(shared_state):
    for name in CONTRACT_TOOLS:
        assert callable(getattr(shared_state, name))
    assert not {
        name
        for name in vars(shared_state)
        if name.startswith("kanban_") and callable(getattr(shared_state, name))
    }


@pytest.mark.parametrize(
    ("profile", "read_domains", "write_domains"),
    [
        (
            "lingjun",
            {"infra", "homeassistant", "media", "research", "xp", "social", "tasks", "shared"},
            {"tasks", "shared"},
        ),
        ("companion", {"social", "shared", "xp"}, {"social", "shared"}),
        (
            "ops",
            {"infra", "homeassistant", "media", "shared"},
            {"infra", "homeassistant", "media", "shared"},
        ),
        ("research", {"research", "shared"}, {"research", "shared"}),
        ("xp", {"xp"}, {"xp"}),
        (
            "codex",
            {"infra", "homeassistant", "media", "research", "xp", "social", "tasks", "shared"},
            {"infra"},
        ),
    ],
)
def test_permission_matrix(shared_state, profile, read_domains, write_domains):
    shared_state.PROFILE = profile
    assert {
        domain
        for domain in shared_state.VALID_DOMAINS
        if shared_state._read_ok(domain)
    } == read_domains
    assert {
        domain
        for domain in shared_state.VALID_DOMAINS
        if shared_state._write_ok(domain)
    } == write_domains


def test_cross_profile_fact_and_observation_flow(shared_state):
    shared_state.PROFILE = "ops"
    assert shared_state.commit_fact(
        "infra", "gateway", '{"status":"healthy"}'
    ).startswith("OK ")
    assert shared_state.record_observation(
        "infra", '{"kind":"restart","ok":true}'
    ).startswith("OK ")

    shared_state.PROFILE = "lingjun"
    resource = json.loads(shared_state.get_resource("infra", "gateway"))
    assert resource["value"] == {"status": "healthy"}
    assert resource["source_profile"] == "ops"
    events = json.loads(shared_state.list_events("infra"))
    assert events[0]["payload"] == {"kind": "restart", "ok": True}


def test_permissions_are_enforced_by_tools(shared_state):
    shared_state.PROFILE = "companion"
    assert shared_state.get_context("infra").startswith("DENIED:")
    assert shared_state.commit_fact("xp", "x", '"no"').startswith("DENIED:")

    shared_state.PROFILE = "ops"
    assert shared_state.get_context("tasks").startswith("DENIED:")


def test_free_text_is_rejected(shared_state):
    shared_state.PROFILE = "research"
    result = shared_state.commit_fact(
        "research", "claim", "this is an unstructured inference paragraph"
    )
    assert result.startswith("REJECTED:")


def test_codex_instructions_name_baseline_resources(shared_state):
    assert "infra/host_environment" in shared_state.SERVER_INSTRUCTIONS
    assert "infra/container_summary" in shared_state.SERVER_INSTRUCTIONS
    assert "infra/container_inventory" in shared_state.SERVER_INSTRUCTIONS
    assert "Codex may write only" in shared_state.SERVER_INSTRUCTIONS
    assert "Collector-owned baseline keys are" in shared_state.SERVER_INSTRUCTIONS
    assert "read the exact resource back" in shared_state.SERVER_INSTRUCTIONS


def test_codex_can_write_only_non_collector_infra(shared_state):
    shared_state.PROFILE = "codex"

    assert shared_state.commit_fact(
        "infra",
        "reverse_proxy_ingress",
        '{"https_public_ipv4_port":28443}',
    ).startswith("OK ")
    resource = json.loads(
        shared_state.get_resource("infra", "reverse_proxy_ingress")
    )
    assert resource["value"] == {"https_public_ipv4_port": 28443}
    assert resource["source_profile"] == "codex"

    assert shared_state.record_observation(
        "infra", '{"kind":"tls_probe","ok":true}'
    ).startswith("OK ")
    assert shared_state.commit_fact(
        "shared", "cross_domain", '{"ok":false}'
    ).startswith("DENIED:")


@pytest.mark.parametrize(
    "key",
    [
        "host_environment",
        "container_summary",
        "container_inventory",
        "host",
        "containers",
    ],
)
def test_codex_cannot_overwrite_collector_owned_infra_keys(
    shared_state, key
):
    shared_state.PROFILE = "codex"
    assert shared_state.commit_fact(
        "infra", key, '{"tampered":true}'
    ).startswith("DENIED:")


def test_trusted_collector_cli_commits_stdin_json(tmp_path):
    db_path = tmp_path / "collector.db"
    result = subprocess.run(
        [
            sys.executable,
            str(SOURCE),
            "--profile",
            "ops",
            "--db",
            str(db_path),
            "--commit-domain",
            "infra",
            "--commit-key",
            "host_environment",
        ],
        input='{"schema_version":1,"host":{"hostname":"test-host"}}',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK commit_fact infra/host_environment"

    shared_state_db = sqlite3.connect(db_path)
    row = shared_state_db.execute(
        "SELECT value,source_profile FROM facts WHERE domain=? AND key=?",
        ("infra", "host_environment"),
    ).fetchone()
    assert row == (
        '{"schema_version": 1, "host": {"hostname": "test-host"}}',
        "ops",
    )
