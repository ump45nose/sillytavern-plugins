import unittest
from unittest.mock import AsyncMock
from common.interventions import fingerprint, IDENTITY
from platforms.epic.workflow import ClaimWorkflow, Offer, Obstacle


class Journal:
    def __init__(self):
        self.states = {}

    async def read(self, key):
        return self.states.get(key)

    async def write(self, key, value):
        self.states[key] = value


class Driver:
    def __init__(self):
        self.journal = Journal()
        self.obstacles = []
        self.observed = 0
        self.offers = [Offer("a", "https://store.epicgames.com/en-US/p/fixture", True)]
        self.cart = "empty_confirmed"
        self.total = "explicit_zero"
        self.submitted = []
        self.recovered = []
        self.submit_error = False
        self.owned = False

    async def observe(self, phase, **kw):
        self.observed += 1
        return self.obstacles[0] if self.obstacles else None

    async def recover(self, state, **kw):
        self.recovered.append(state.kind)
        self.obstacles.pop(0)

    async def inventory(self, **kw):
        return self.offers

    async def open_offer(self, offer, **kw):
        pass

    async def verify(self, offer, **kw):
        return "owned" if self.owned or offer.id in self.submitted else "not_owned"

    async def inspect_cart(self, **kw):
        return self.cart

    async def prepare_checkout(self, offer, **kw):
        pass

    async def checkout_total(self, **kw):
        return self.total

    async def submit_once(self, offer, **kw):
        self.submitted.append(offer.id)
        if self.submit_error:
            raise TimeoutError("fixture")


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def engine(self, driver, **kw):
        return ClaimWorkflow(
            driver,
            {"run_id": "fixture", "platform": "epic", "account": "one"},
            deadline=100,
            expires_at="2099-01-01T00:00:00Z",
            clock=lambda: 0,
            sleep=AsyncMock(),
            **kw,
        )

    async def test_claim_once_verify(self):
        d = Driver()
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(d.submitted, ["a"])
        self.assertEqual(d.journal.states["a"], "confirmed")

    async def test_direct_zero_checkout_preserves_unrelated_paid_cart(self):
        d = Driver()
        d.cart = "paid_or_unknown"
        d.checkout_uses_cart = AsyncMock(return_value=False)
        d.inspect_cart = AsyncMock(return_value=d.cart)
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(d.submitted, ["a"])
        d.inspect_cart.assert_not_awaited()
        self.assertEqual(d.cart, "paid_or_unknown")

    async def test_direct_route_still_requires_explicit_zero_checkout(self):
        d = Driver()
        d.cart = "paid_or_unknown"
        d.checkout_uses_cart = AsyncMock(return_value=False)
        d.total = "unknown"
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "checkout_price_unconfirmed")
        self.assertEqual(d.submitted, [])

    async def test_cart_route_preserves_paid_cart_before_prepare(self):
        d = Driver()
        d.cart = "paid_or_unknown"
        d.checkout_uses_cart = AsyncMock(return_value=True)
        d.prepare_checkout = AsyncMock()
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "cart_preserved")
        self.assertEqual(d.submitted, [])
        d.prepare_checkout.assert_not_awaited()

    async def test_delayed_ownership_reconciled_without_repeat(self):
        d = Driver()
        d.verify = AsyncMock(side_effect=["not_owned", "unknown", "not_owned", "owned"])
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(r.confirmed, ["a"])
        self.assertEqual(d.submitted, ["a"])
        self.assertEqual(d.verify.await_count, 4)

    async def test_pending_intent_later_confirmed_without_submit(self):
        d = Driver()
        d.journal.states["a"] = "submitting"
        d.verify = AsyncMock(side_effect=["unknown", "unknown", "owned"])
        r = await self.engine(d).run()
        self.assertEqual(r.already_owned, ["a"])
        self.assertEqual(r.uncertain, [])
        self.assertEqual(d.submitted, [])

    async def test_readback_transport_failure_retried_readonly(self):
        d = Driver()
        d.verify = AsyncMock(side_effect=["not_owned", TimeoutError(), "owned"])
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(d.submitted, ["a"])

    async def test_unconfirmed_readback_bounded(self):
        d = Driver()
        d.verify = AsyncMock(return_value="unknown")
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "partial")
        self.assertEqual(r.uncertain, ["a"])
        self.assertEqual(d.verify.await_count, 4)
        self.assertEqual(d.submitted, ["a"])

    async def test_post_submit_stale_obstacle_readback_before_approval(self):
        d = Driver()
        original = d.submit_once

        async def submit(offer, **kw):
            await original(offer, **kw)
            d.obstacles = [
                Obstacle("captcha", "fixture", fingerprint("late"), "post_submit")
            ]

        d.submit_once = submit
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(r.confirmed, ["a"])
        self.assertEqual(r.pending, [])
        self.assertEqual(d.submitted, ["a"])

    async def test_unconfirmed_submit_still_requires_challenge_approval(self):
        d = Driver()
        original = d.submit_once

        async def submit(offer, **kw):
            await original(offer, **kw)
            d.obstacles = [
                Obstacle("captcha", "fixture", fingerprint("late"), "post_submit")
            ]

        d.submit_once = submit
        d.verify = AsyncMock(return_value="unknown")
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "approval_or_handler_needed")
        self.assertEqual(r.uncertain, ["a"])
        self.assertEqual(d.verify.await_count, 4)
        self.assertEqual(d.submitted, ["a"])

    async def test_post_submit_recovered_gate_then_readback_never_resubmits(self):
        d = Driver()
        original = d.submit_once

        async def submit(offer, **kw):
            await original(offer, **kw)
            d.obstacles = [
                Obstacle("captcha", "fixture", fingerprint("late"), "post_submit")
            ]

        async def approve(req):
            return {
                **{k: req[k] for k in IDENTITY},
                "decision": "approve",
                "expires_at": "2099-01-01T00:00:00Z",
            }

        async def solver(*a, **kw):
            d.obstacles.clear()

        d.submit_once = submit
        d.verify_readonly = AsyncMock(
            side_effect=["unknown", "unknown", "unknown", "owned"]
        )
        r = await self.engine(d, approve=approve, handlers={"captcha": solver}).run()
        self.assertEqual(r.confirmed, ["a"])
        self.assertEqual(d.submitted, ["a"])

    async def test_already_owned_no_submit(self):
        d = Driver()
        d.owned = True
        r = await self.engine(d).run()
        self.assertEqual(r.already_owned, ["a"])
        self.assertEqual(d.submitted, [])

    async def test_paid_cart_preserved(self):
        d = Driver()
        d.cart = "paid"
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "cart_preserved")
        self.assertEqual(d.submitted, [])

    async def test_price_unknown_no_submit(self):
        d = Driver()
        d.total = "unknown"
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "checkout_price_unconfirmed")
        self.assertEqual(d.submitted, [])

    async def test_submission_timeout_readback_not_replay(self):
        d = Driver()
        d.submit_error = True
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(d.submitted, ["a"])

    async def test_pending_intent_no_replay(self):
        d = Driver()
        d.journal.states["a"] = "submitting"
        r = await self.engine(d).run()
        self.assertEqual(r.uncertain, ["a"])
        self.assertEqual(d.submitted, [])

    async def test_confirmed_history_not_replayed_on_unknown(self):
        d = Driver()
        d.journal.states["a"] = "confirmed"

        async def unknown(*a, **kw):
            return "unknown"

        d.verify = unknown
        r = await self.engine(d).run()
        self.assertEqual(r.uncertain, ["a"])
        self.assertEqual(d.submitted, [])

    async def test_transient_obstacle_recovered(self):
        d = Driver()
        d.obstacles = [Obstacle("popup", "fixture", fingerprint("popup"), "product")]
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(d.recovered, ["popup"])

    async def test_captcha_pending_is_not_deleted_capability(self):
        d = Driver()
        d.obstacles = [
            Obstacle("captcha", "fixture", fingerprint("captcha"), "session")
        ]
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "approval_or_handler_needed")
        self.assertEqual(r.pending[0]["kind"], "captcha")
        self.assertEqual(d.submitted, [])

    async def test_approved_handler_resumes_and_reobserves(self):
        d = Driver()
        d.obstacles = [
            Obstacle("captcha", "fixture", fingerprint("captcha"), "session")
        ]

        async def approve(req):
            return {
                **{k: req[k] for k in IDENTITY},
                "decision": "approve",
                "expires_at": "2099-01-01T00:00:00Z",
            }

        called = []

        async def solver(state, **kw):
            called.append(state.kind)
            d.obstacles.clear()

        r = await self.engine(d, approve=approve, handlers={"captcha": solver}).run()
        self.assertEqual(r.reason, "complete")
        self.assertEqual(called, ["captcha"])
        self.assertGreater(d.observed, 2)

    async def test_denied_no_handler(self):
        d = Driver()
        d.obstacles = [Obstacle("terms", "fixture", fingerprint("terms"), "checkout")]

        async def deny(req):
            return {"decision": "deny"}

        async def fail(*a, **kw):
            raise AssertionError("must not execute")

        r = await self.engine(d, approve=deny, handlers={"terms": fail}).run()
        self.assertEqual(r.reason, "approval_not_granted")
        self.assertEqual(d.submitted, [])

    async def test_rate_limit_does_not_retry(self):
        d = Driver()
        d.obstacles = [
            Obstacle("rate_limited", "fixture", fingerprint("limit"), "checkout")
        ]
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "rate_limited")
        self.assertEqual(d.recovered, [])

    async def test_missing_inventory_not_empty_success(self):
        d = Driver()
        d.offers = []
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "inventory_unconfirmed")

    async def test_not_free_preserves_no_action(self):
        d = Driver()
        d.offers = [Offer("a", "https://store.epicgames.com/en-US/p/fixture", False)]
        r = await self.engine(d).run()
        self.assertEqual(r.reason, "partial")
        self.assertEqual(d.submitted, [])


if __name__ == "__main__":
    unittest.main()
