"""Behavior tests for the local shared-state MCP contract."""

from __future__ import annotations

import importlib.util
import json
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
