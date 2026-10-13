import unittest
from types import SimpleNamespace
from platforms.epic.challenges import HCaptchaHandler
from platforms.epic.workflow import Obstacle
from common.interventions import fingerprint


class ChallengeTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_import_at_construction(self):
        calls = []
        HCaptchaHandler(object(), object(), loader=lambda name: calls.append(name))
        self.assertEqual(calls, [])

    async def test_solver_response_needs_fresh_readback(self):
        calls = []

        class Agent:
            def __init__(self, **kw):
                calls.append("construct")

            async def wait_for_challenge(self):
                calls.append("attempt")
                return SimpleNamespace(value="success")

            async def aclose(self):
                calls.append("close")

        h = HCaptchaHandler(
            object(), object(), loader=lambda name: SimpleNamespace(AgentV=Agent)
        )
        out = await h.handle(
            Obstacle("captcha", "fixture", fingerprint("x"), "checkout"), timeout=1
        )
        self.assertTrue(out["requires_readback"])
        self.assertNotIn("business_success", out)
        await h.close()
        self.assertEqual(calls, ["construct", "attempt", "close"])

    async def test_nonchallenge_does_not_import(self):
        calls = []
        h = HCaptchaHandler(None, None, loader=lambda name: calls.append(name))
        with self.assertRaises(ValueError):
            await h.handle(
                Obstacle("terms", "fixture", fingerprint("x"), "checkout"), timeout=1
            )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
