"""Resumable-action scope protocol, not an identity/authorization service.

The caller obtains decisions through a trusted user-approval channel. A JSON
file, model assertion or flag is NOT proof of human consent. This module only
checks scope/freshness, and never performs a browser action. Checkpoints must
not contain cookies, passwords, DOB, raw HTML or screenshots.
"""

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid

KINDS = {
    "captcha",
    "terms",
    "age_verification",
    "login",
    "account_link",
    "security_prompt",
    "account_setting",
}
IDENTITY = (
    "request_id",
    "platform",
    "account",
    "capability",
    "kind",
    "target",
    "fingerprint",
)
MAX_CHECKPOINT = 8192


def fingerprint(*parts):
    """Hash safe caller-selected evidence, not an entire secret page."""
    encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode()
    if len(encoded) > 65536:
        raise ValueError("evidence_too_large")
    return hashlib.sha256(encoded).hexdigest()


def _time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_required")
    return parsed.astimezone(timezone.utc)


def request(
    context, capability, phase, kind, target, evidence_fingerprint, *, expires_at
):
    """target is a safe identifier or clean official URL without secret query data."""
    return validate_request(
        {
            "schema_version": 1,
            "request_id": str(uuid.uuid4()),
            "origin_run_id": context["run_id"],
            "platform": context["platform"],
            "account": context["account"],
            "capability": capability,
            "phase": phase,
            "kind": kind,
            "target": target,
            "fingerprint": evidence_fingerprint,
            "expires_at": expires_at,
            "resume_policy": "readback_then_revalidate",
        }
    )


def validate_request(value):
    allowed = set(IDENTITY) | {
        "schema_version",
        "origin_run_id",
        "phase",
        "expires_at",
        "resume_policy",
    }
    if (
        not isinstance(value, dict)
        or set(value) != allowed
        or value["schema_version"] != 1
    ):
        raise ValueError("invalid_checkpoint_schema")
    if not isinstance(value["kind"], str) or value["kind"] not in KINDS:
        raise ValueError("unsupported_intervention")
    for key in IDENTITY + ("origin_run_id", "phase", "expires_at"):
        if not isinstance(value[key], str) or not value[key] or len(value[key]) > 1024:
            raise ValueError("invalid_checkpoint_field")
    for key in ("platform", "account", "capability", "phase"):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", value[key]):
            raise ValueError("invalid_checkpoint_identifier")
    if not re.fullmatch(r"[a-f0-9]{64}", value["fingerprint"]):
        raise ValueError("invalid_fingerprint")
    if value["resume_policy"] != "readback_then_revalidate":
        raise ValueError("invalid_resume_policy")
    if len(json.dumps(value).encode()) > MAX_CHECKPOINT:
        raise ValueError("checkpoint_too_large")
    _time(value["expires_at"])
    return dict(value)


def validate_resume(value, decision, current_fingerprint, *, now=None):
    """Validate a TRUSTED caller decision, not arbitrary disk JSON.

    Caller first reads current site state: already completed means reconcile,
    not replay. Then verify real consent where required before this function.
    Terms bind exact URL/text/version; truthful age data stays outside checkpoint.
    A None return means scope matches, not that this module authenticated anyone.
    """
    try:
        value = validate_request(value)
        if not isinstance(decision, dict):
            return "approval_missing"
        if decision.get("decision") != "approve":
            return "approval_not_granted"
        if any(decision.get(key) != value[key] for key in IDENTITY):
            return "approval_scope_mismatch"
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            return "invalid_clock"
        if clock >= _time(value["expires_at"]) or clock >= _time(
            decision["expires_at"]
        ):
            return "approval_expired"
        if current_fingerprint != value["fingerprint"]:
            return "site_state_changed"
        return None
    except (KeyError, TypeError, ValueError, AttributeError):
        return "invalid_approval_or_checkpoint"
