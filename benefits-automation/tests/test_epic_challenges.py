import unittest
import contextlib
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from platforms.epic.challenges import HCaptchaHandler, _sdk_error
from platforms.epic.workflow import Obstacle, Paused
from platforms.epic.native import Login
from common.interventions import fingerprint


class ChallengeTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_solver_or_timeout_stops_without_repeating_the_challenge(self):
        for expected, handle in [
            ("challenge_unconfirmed", AsyncMock(return_value={"solver_signal": "failure"})),
            ("challenge_timeout", AsyncMock(side_effect=TimeoutError())),
            ("challenge_timeout", AsyncMock(return_value={"solver_signal": "challenge_execution_timeout"})),
            ("challenge_timeout", AsyncMock(return_value={"solver_signal": "challenge_response_timeout"})),
        ]:
            auth = Login(SimpleNamespace(page=SimpleNamespace(frames=[])), {})
            auth.challenge = SimpleNamespace(handle=handle)
            with self.assertRaises(Paused) as raised:
                await auth.captcha(Obstacle("captcha", "fixture", fingerprint("x"), "checkout"), timeout=1)
            self.assertEqual(raised.exception.reason, expected)
            handle.assert_awaited_once()

    def test_sdk_swallowed_error_keeps_location_without_private_message_or_response(self):
        stream = io.StringIO()
        message = SimpleNamespace(record={"exception": SimpleNamespace(type=ValueError),
            "file": SimpleNamespace(name="challenger.py"), "line": 904,
            "function": "_solve_captcha", "message": "private-token-and-model-response"})
        with contextlib.redirect_stdout(stream):
            _sdk_error(message)
        self.assertEqual(json.loads(stream.getvalue()), {"event": "epic_challenge_error",
            "source": "challenger.py", "line": 904, "function": "_solve_captcha", "type": "ValueError"})
        self.assertNotIn("private-token", stream.getvalue())

    async def test_no_import_at_construction(self):
        calls = []
        HCaptchaHandler(object(), object(), loader=lambda name: calls.append(name))
        self.assertEqual(calls, [])

    async def test_sdk_error_sink_is_removed_when_the_solver_raises(self):
        try:
            from loguru import logger
        except ImportError:
            self.skipTest("optional challenge SDK logging unavailable")
        class Agent:
            def __init__(self, **kwargs):
                pass
            async def wait_for_challenge(self):
                logger.error("private-token-and-model-response")
                raise ValueError("private-token-and-model-response")
        handler = HCaptchaHandler(None, None, loader=lambda _: SimpleNamespace(AgentV=Agent))
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream), self.assertRaises(ValueError):
            await handler.handle(Obstacle("captcha", "fixture", fingerprint("x"), "checkout"), timeout=1)
        self.assertEqual(json.loads(stream.getvalue())["event"], "epic_challenge_error")
        self.assertNotIn("private-token", stream.getvalue())
        self.assertFalse(logger._core.handlers)

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
