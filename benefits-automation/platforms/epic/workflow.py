"""Epic claim state machine with injected browser/obstacle handlers.

Business operations are independent of the concrete browser and challenge SDK.
"""

from dataclasses import dataclass, field
import time
import asyncio
from typing import Any
from urllib.parse import urlsplit
from common.interventions import request, validate_resume

# Consent-bearing steps and recoverable non-consent obstacles are distinct.
CONSENT = {
    "captcha",
    "terms",
    "age_verification",
    "login",
    "account_link",
    "security_prompt",
    "account_setting",
}
RECOVERABLE = {
    "navigation_partial",
    "store_sso",
    "overlay",
    "popup",
    "stale_locator",
    "delayed_result",
    "browser_page_rebuild",
    "region_layout",
    "mfa_code_expired",
}
TERMINAL = {"rate_limited", "account_restricted", "unsupported_region", "unknown"}


@dataclass(frozen=True)
class Obstacle:
    kind: str
    target: str
    fingerprint: str
    phase: str
    # Only a clean target and fingerprint may be exported in a checkpoint.
    payload: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class Offer:
    id: str
    url: str
    explicitly_free: bool
    title: str = ""


@dataclass
class ClaimResult:
    offers: list[Offer] = field(default_factory=list)
    inventory_complete: bool = False
    confirmed: list[str] = field(default_factory=list)
    already_owned: list[str] = field(default_factory=list)
    uncertain: list[str] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    reason: str = "unknown"


class Paused(Exception):
    def __init__(self, reason, checkpoint=None):
        self.reason = reason
        self.checkpoint = checkpoint


class ClaimWorkflow:
    """Driver operations remain explicit: observation, recovery, submit, verify.

    driver.journal must persist submission intent before a side-effect. An
    ambiguous prior intent is never treated as permission to click again.
    Trusted approval callback is separate from plugin execution and disk files.
    """

    def __init__(
        self,
        driver,
        context,
        *,
        deadline,
        expires_at,
        approve=None,
        handlers=None,
        automatic_kinds=(),
        clock=time.monotonic,
        readback_attempts=3,
        readback_interval=2,
        sleep=asyncio.sleep,
    ):
        if type(readback_attempts) is not int or not 1 <= readback_attempts <= 10:
            raise ValueError("invalid_readback_attempts")
        if (
            type(readback_interval) not in (int, float)
            or not 0 <= readback_interval <= 30
        ):
            raise ValueError("invalid_readback_interval")
        self.readback_attempts = readback_attempts
        self.readback_interval = readback_interval
        self.sleep = sleep
        self.driver = driver
        self.context = context
        self.deadline = deadline
        self.expires_at = expires_at
        self.approve = approve
        self.handlers = handlers or {}
        self.automatic_kinds = frozenset(automatic_kinds)
        self.clock = clock
        self.remaining_recoveries = 12
        self.remaining_interventions = 8

    def remaining(self):
        remaining = self.deadline - self.clock()
        if remaining <= 0:
            raise Paused("deadline_exceeded")
        return remaining

    async def settle(self, phase):
        """Observe after every recovery; solver success is not business success."""
        handled = False
        while True:
            state = await self.driver.observe(phase, timeout=self.remaining())
            if state is None:
                return handled
            if not isinstance(state, Obstacle):
                raise Paused("invalid_observation")
            if state.kind in TERMINAL:
                raise Paused(phase + "_state_unconfirmed" if state.kind == "unknown" else state.kind)
            if state.kind in RECOVERABLE:
                if self.remaining_recoveries <= 0:
                    raise Paused("recovery_budget_exhausted")
                self.remaining_recoveries -= 1
                # Recovery bindings must not submit orders, erase sessions, or
                # silently accept terms. Those are separate explicit operations.
                await self.driver.recover(state, timeout=self.remaining())
                handled = True
                continue
            if state.kind not in CONSENT:
                raise Paused("unsupported_obstacle")
            if state.kind in self.automatic_kinds and state.kind in self.handlers:
                # Public --execute may bind already-authorized routine login and
                # challenge operations locally. No fabricated host approval.
                if self.remaining_interventions <= 0:
                    raise Paused("intervention_budget_exhausted")
                self.remaining_interventions -= 1
                await self.handlers[state.kind](state, timeout=self.remaining())
                handled = True
                continue
            pending = request(
                self.context,
                "claim",
                state.phase,
                state.kind,
                state.target,
                state.fingerprint,
                expires_at=self.expires_at,
            )
            if self.remaining_interventions <= 0:
                raise Paused("intervention_budget_exhausted", pending)
            if self.approve is None or state.kind not in self.handlers:
                raise Paused("approval_or_handler_needed", pending)
            # Callback must authenticate user consent via the host, not read an
            # arbitrary approval JSON. Missing truthful age/OTP data is handled
            # inside the selected handler, never substituted by a default.
            decision = await asyncio.wait_for(
                self.approve(pending), timeout=self.remaining()
            )
            current = await self.driver.observe(phase, timeout=self.remaining())
            if current is None:
                handled = True
                continue  # Already resolved: do not replay.
            if (
                not isinstance(current, Obstacle)
                or current.kind != state.kind
                or current.target != state.target
            ):
                raise Paused("site_state_changed", pending)
            error = validate_resume(pending, decision, current.fingerprint)
            if error:
                raise Paused(error, pending)
            self.remaining_interventions -= 1
            await self.handlers[state.kind](current, timeout=self.remaining())
            handled = True
            # Always re-observe; don't trust a plugin's own success flag.

    async def reconcile(self, offer):
        """Bounded read-only recovery for delayed ownership; never resubmit."""
        for attempt in range(self.readback_attempts):
            if attempt:
                await asyncio.wait_for(
                    self.sleep(min(self.readback_interval, self.remaining())),
                    timeout=self.remaining(),
                )
            try:
                # Independent readback must precede interaction with a stale
                # checkout gate. BrowserDriver uses a separate, finally-closed
                # page so an unfinished transaction remains available.
                verify = getattr(self.driver, "verify_readonly", self.driver.verify)
                state = await asyncio.wait_for(
                    verify(offer, timeout=self.remaining()),
                    timeout=self.remaining(),
                )
            except (TimeoutError, ConnectionError):
                continue
            if state == "owned":
                return True
        return False

    async def run(self):
        out = ClaimResult()
        try:
            await self.settle("session")
            offers = await self.driver.inventory(timeout=self.remaining())
            from .catalog import Inventory

            if isinstance(offers, Inventory):
                if not offers.complete:
                    raise Paused("inventory_unconfirmed")
                if not offers.offers:
                    out.inventory_complete = True
                    out.reason = "no_current_promotions"
                    return out
                offers = offers.offers
            if not isinstance(offers, list) or not offers:
                raise Paused("inventory_unconfirmed")
            if len(offers) > 200 or any(not isinstance(o, Offer) for o in offers):
                raise Paused("inventory_invalid")
            ids = [o.id for o in offers]
            if len(set(ids)) != len(ids):
                raise Paused("inventory_ambiguous")
            out.offers = offers
            out.inventory_complete = True
            for offer in offers:
                parsed = urlsplit(offer.url)
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != "store.epicgames.com"
                    or parsed.username
                    or parsed.password
                    or parsed.port not in (None, 443)
                    or not offer.id
                    or len(offer.id) > 128
                ):
                    raise Paused("invalid_offer_target")
                if offer.explicitly_free is not True:
                    out.uncertain.append(offer.id)
                    continue
                await self.driver.open_offer(offer, timeout=self.remaining())
                await self.settle("product")
                owned = await self.driver.verify(offer, timeout=self.remaining())
                if owned == "owned":
                    out.already_owned.append(offer.id)
                    continue
                if owned not in {"not_owned", "unknown"}:
                    out.uncertain.append(offer.id)
                    continue
                prior = await self.driver.journal.read(offer.id)
                if prior in {"submitting", "submitted", "uncertain", "confirmed"}:
                    # Uncertain previous submissions require readback, not replay.
                    out.uncertain.append(offer.id)
                    if await self.reconcile(offer):
                        await self.driver.journal.write(offer.id, "confirmed")
                        out.uncertain.remove(offer.id)
                        out.already_owned.append(offer.id)
                    continue
                # Direct product checkout must still bind one exact offer and
                # zero total below. An unrelated paid cart remains untouched.
                # Drivers without verified route observation retain cart checks.
                route = getattr(self.driver, "checkout_uses_cart", None)
                uses_cart = await route(offer, timeout=self.remaining()) if route else True
                if type(uses_cart) is not bool:
                    raise Paused("purchase_control_unknown")
                if uses_cart:
                    prepare_cart = getattr(self.driver, "prepare_cart", None)
                    if prepare_cart is not None:
                        await prepare_cart(timeout=self.remaining())
                        await self.settle("cart")
                    cart = await self.driver.inspect_cart(timeout=self.remaining())
                    if cart not in {"empty_confirmed", "only_free_confirmed"}:
                        raise Paused("cart_preserved")
                await self.driver.prepare_checkout(offer, timeout=self.remaining())
                await self.settle("checkout")
                total = await self.driver.checkout_total(timeout=self.remaining())
                if total != "explicit_zero":
                    raise Paused("checkout_price_unconfirmed")
                await self.driver.journal.write(offer.id, "submitting")
                out.uncertain.append(offer.id)
                try:
                    await self.driver.submit_once(offer, timeout=self.remaining())
                    await self.driver.journal.write(offer.id, "submitted")
                except Exception:
                    await self.driver.journal.write(offer.id, "uncertain")
                # No submission retries, including after navigation timeout.
                reconciled = await self.reconcile(offer)
                if not reconciled and await self.settle("post_submit"):
                    reconciled = await self.reconcile(offer)
                if reconciled:
                    await self.driver.journal.write(offer.id, "confirmed")
                    out.confirmed.append(offer.id)
                    out.uncertain.remove(offer.id)
                else:
                    await self.driver.journal.write(offer.id, "uncertain")
            out.reason = "complete" if not out.uncertain else "partial"
        except Paused as error:
            out.reason = error.reason
            if error.checkpoint:
                out.pending.append(error.checkpoint)
        except Exception as error:
            # SDK/browser messages may contain session tokens. Keep locations
            # and exception type so an operational failure remains diagnosable.
            import json
            import traceback
            from pathlib import Path
            print(json.dumps({"event": "epic_driver_error", "type": type(error).__name__,
                "frames": [f"{Path(row.filename).name}:{row.lineno}:{row.name}"
                           for row in traceback.extract_tb(error.__traceback__)[-6:]]}), flush=True)
            out.reason = "driver_error"
        return out
