"""Pure obstacle classification and lazy handler lifecycle.

Browser observation bindings remain separate and must supply current evidence.
Classification never clicks a button or interprets a solver return as ownership.
"""

import inspect
import asyncio
from .workflow import Obstacle


def classify(signals, *, phase, target, evidence_fingerprint):
    """Inputs are explicit observations, not guesses from missing DOM fields."""
    if not isinstance(signals, dict):
        return Obstacle("unknown", target, evidence_fingerprint, phase)
    # Permanent/account limits outrank recoverable UI or challenge indicators.
    for name in ("rate_limited", "account_restricted", "unsupported_region"):
        if signals.get(name) is True:
            return Obstacle(name, target, evidence_fingerprint, phase)
    # A terms/age choice cannot be hidden behind a generic Continue/modal step.
    for flag, kind in (
        ("new_terms", "terms"),
        ("privacy_acceptance", "terms"),
        ("age_confirmation", "age_verification"),
        ("account_link", "account_link"),
        ("security_setting", "security_prompt"),
        ("visible_captcha", "captcha"),
        ("mfa_required", "login"),
        ("login_required", "login"),
        ("remembered_account", "login"),
        ("store_sso", "store_sso"),
        ("device_modal", "region_layout"),
        ("stale_locator", "stale_locator"),
        ("navigation_partial", "navigation_partial"),
        ("safe_overlay", "overlay"),
        ("delayed_result", "delayed_result"),
    ):
        if signals.get(flag) is True:
            return Obstacle(
                kind, target, evidence_fingerprint, phase, payload={"subtype": flag}
            )
    if signals.get("ready") is True:
        return None
    return Obstacle("unknown", target, evidence_fingerprint, phase)


class LazyHandler:
    """Instantiate an approved integration only when its obstacle occurs.

    The workflow validates authorization before invoking this handler. The
    integration is responsible for truthful supplied data, intended destination,
    and per-challenge semantics. Factory must never be constructed at startup.
    """

    def __init__(self, factory):
        self.factory = factory

    async def __call__(self, obstacle, *, timeout):
        if timeout <= 0:
            raise TimeoutError("deadline_exceeded")
        handler = self.factory()
        if inspect.isawaitable(handler):
            handler = await asyncio.wait_for(handler, timeout=timeout)
        try:
            # A bounded attempt. Further attempts require fresh page observation,
            # not internal unbounded retry or repeat order submission.
            return await asyncio.wait_for(
                handler.handle(obstacle, timeout=timeout), timeout=timeout
            )
        finally:
            close = getattr(handler, "close", None)
            if close:
                result = close()
                if inspect.isawaitable(result):
                    await asyncio.wait_for(result, timeout=2)
