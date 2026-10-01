import unittest
from platforms.epic.obstacles import classify, LazyHandler
from common.interventions import fingerprint
from platforms.epic.workflow import Obstacle


class ObstacleTests(unittest.TestCase):
    def classify(self, signals):
        return classify(
            signals,
            phase="checkout",
            target="fixture",
            evidence_fingerprint=fingerprint("fixture"),
        )

    def test_requires_positive_ready_evidence(self):
        self.assertEqual(self.classify({}).kind, "unknown")
        self.assertIsNone(self.classify({"ready": True}))

    def test_age_not_generic_continue(self):
        self.assertEqual(
            self.classify({"age_confirmation": True, "safe_overlay": True}).kind,
            "age_verification",
        )

    def test_terms_not_generic_overlay(self):
        self.assertEqual(
            self.classify({"new_terms": True, "safe_overlay": True}).kind, "terms"
        )

    def test_account_limit_not_captcha_retry(self):
        self.assertEqual(
            self.classify({"rate_limited": True, "visible_captcha": True}).kind,
            "rate_limited",
        )

    def test_mfa_retained(self):
        self.assertEqual(
            self.classify({"mfa_required": True}).payload["subtype"], "mfa_required"
        )

    def test_recoverable_families(self):
        for flag, kind in [
            ("remembered_account", "remembered_account"),
            ("store_sso", "store_sso"),
            ("device_modal", "region_layout"),
            ("stale_locator", "stale_locator"),
            ("navigation_partial", "navigation_partial"),
            ("safe_overlay", "overlay"),
            ("delayed_result", "delayed_result"),
        ]:
            self.assertEqual(self.classify({flag: True}).kind, kind)


class LazyTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_startup_or_idle_solver(self):
        calls = []
        h = LazyHandler(lambda: calls.append("load"))
        self.assertEqual(calls, [])
        with self.assertRaises(TimeoutError):
            await h(
                Obstacle("captcha", "fixture", fingerprint("x"), "checkout"), timeout=0
            )
        self.assertEqual(calls, [])

    async def test_close_after_success(self):
        calls = []

        class Handler:
            async def handle(self, obstacle, timeout):
                calls.append("attempt")
                return "needs_readback"

            async def close(self):
                calls.append("close")

        h = LazyHandler(lambda: Handler())
        self.assertEqual(
            await h(
                Obstacle("captcha", "fixture", fingerprint("x"), "checkout"), timeout=3
            ),
            "needs_readback",
        )
        self.assertEqual(calls, ["attempt", "close"])

    async def test_close_after_failure(self):
        calls = []

        class Handler:
            async def handle(self, *a, **kw):
                raise RuntimeError("fixture")

            async def close(self):
                calls.append("close")

        h = LazyHandler(lambda: Handler())
        with self.assertRaises(RuntimeError):
            await h(
                Obstacle("captcha", "fixture", fingerprint("x"), "checkout"), timeout=3
            )
        self.assertEqual(calls, ["close"])


if __name__ == "__main__":
    unittest.main()
