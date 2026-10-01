"""Validate an untrusted child signal and create a pending request, never a grant."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from .interventions import request, KINDS, MAX_CHECKPOINT

REWARDS_HOSTS = {
    "rewards.bing.com",
    "www.bing.com",
    "cn.bing.com",
    "bing.com",
    "login.live.com",
    "account.live.com",
    "login.microsoftonline.com",
    "www.microsoft.com",
    "account.microsoft.com",
    "privacy.microsoft.com",
}
FIELDS = {
    "schema_version",
    "run_id",
    "platform",
    "account",
    "capability",
    "phase",
    "kind",
    "target",
    "fingerprint",
    "ttl_seconds",
}
CAPABILITIES = {
    "desktop-search": {"desktop_search"},
    "mobile-search": {"mobile_search"},
    "activities": {"daily"},
    "punchcards": {"punchcards"},
    "snapshot": {"snapshot"},
    "extra": {"extra", "goal"},
    "full": {
        "daily",
        "snapshot",
        "extra",
        "goal",
        "desktop_search",
        "mobile_search",
        "claim",
        "punchcards",
        "app_daily",
        "app_promotions",
        "read_to_earn",
        "bonus_search",
        "visual_search",
        "streak_protection",
        "search_perk",
        "more_promotions",
        "experimental_api_search",
        "experimental_api_search_on_bing",
        "experimental_edge_browsing",
    },
}


def create_checkpoint(signal_path, context, mode, *, now=None):
    path = Path(signal_path)
    if not path.exists():
        return None
    with path.open("rb") as f:
        payload = f.read(MAX_CHECKPOINT + 1)
    if len(payload) > MAX_CHECKPOINT:
        raise ValueError("signal_too_large")
    value = json.loads(payload)
    if (
        not isinstance(value, dict)
        or set(value) != FIELDS
        or value.get("schema_version") != 1
    ):
        raise ValueError("invalid_signal_schema")
    for key in ("run_id", "platform", "account"):
        if value.get(key) != context[key]:
            raise ValueError("signal_identity_mismatch")
    if context["platform"] == "rewards":
        capabilities, hosts = CAPABILITIES.get(mode, set()), REWARDS_HOSTS
    elif context["platform"] == "laowang" and mode == "full":
        capabilities, hosts = {"tncode"}, {"laowang.vip"}
        if value["kind"] != "captcha":
            raise ValueError("unsupported_intervention")
    else:
        raise ValueError("unsupported_signal_platform")
    if (
        not isinstance(value["capability"], str)
        or value["capability"] not in capabilities
    ):
        raise ValueError("signal_capability_mismatch")
    if not isinstance(value["kind"], str) or value["kind"] not in KINDS:
        raise ValueError("unsupported_intervention")
    if not isinstance(value["phase"], str) or not re.fullmatch(
        r"[a-zA-Z0-9_.-]{1,64}", value["phase"]
    ):
        raise ValueError("invalid_phase")
    target = value["target"]
    if not isinstance(target, str) or len(target) > 1024:
        raise ValueError("invalid_target")
    url = urlsplit(target)
    if (
        url.scheme != "https"
        or url.hostname not in hosts
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.port not in (None, 443)
    ):
        raise ValueError("invalid_target")
    ttl = value["ttl_seconds"]
    if isinstance(ttl, bool) or not isinstance(ttl, int) or not 30 <= ttl <= 900:
        raise ValueError("invalid_signal_expiry")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError("invalid_clock")
    return request(
        context,
        value["capability"],
        value["phase"],
        value["kind"],
        target,
        value["fingerprint"],
        expires_at=(clock + timedelta(seconds=ttl)).isoformat(),
    )
