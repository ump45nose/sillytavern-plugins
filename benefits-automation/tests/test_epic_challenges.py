import unittest
import contextlib
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from platforms.epic.challenges import HCaptchaHandler, _sdk_error
from platforms.epic.workflow import Obstacle, Paused
from platforms.epic.native import Login, report_purchase_error
from common.interventions import fingerprint
from dataclasses import replace


class FixtureAgent:
    def __init__(self, **kwargs):
        self.robotic_arm = SimpleNamespace(captcha_payload=None, _challenge_prompt=None,
            _match_user_prompt=lambda _: "JobType: fixture")


class StoreSsoTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        page = SimpleNamespace(url="https://store.epicgames.com/login?redirectTo=%2Fpurchase%3Foffers%3Dfixture",
            wait_for_timeout=AsyncMock())
        driver = SimpleNamespace(page=page, offer=SimpleNamespace(id="fixture"), prepared={"fixture"},
            _goto=AsyncMock(), prepare_checkout=AsyncMock(), submit_once=AsyncMock())
        obstacle = Obstacle("store_sso", "https://store.epicgames.com/login", "fixture", "checkout",
            {"_container": page})
        return driver, obstacle

    async def test_pending_checkout_uses_official_authentication_and_preserves_its_return_target_once(self):
        driver, obstacle = self.fixture()
        auth = Login(driver, {})
        await auth.sso(obstacle, timeout=10)
        target = driver._goto.await_args.args[0]
        self.assertEqual(target, driver.page.url)
        with self.assertRaises(Paused):
            await auth.sso(obstacle, timeout=10)
        driver._goto.assert_awaited_once()
        driver.prepare_checkout.assert_not_awaited()
        driver.submit_once.assert_not_awaited()

    async def test_sso_cannot_redirect_unprepared_or_post_submit_pages(self):
        for change in ["unprepared", "post_submit", "other_container", "other_origin"]:
            driver, obstacle = self.fixture()
            if change == "unprepared": driver.prepared.clear()
            if change == "post_submit": obstacle = replace(obstacle, phase="post_submit")
            if change == "other_container": obstacle.payload["_container"] = object()
            if change == "other_origin": driver.page.url = "https://unrelated.invalid/login"
            with self.subTest(change=change), self.assertRaises(Paused):
                await Login(driver, {}).sso(obstacle, timeout=10)
            driver._goto.assert_not_awaited()

    async def test_signed_out_product_authenticates_before_any_checkout_action(self):
        driver, _ = self.fixture()
        driver.page.url = "https://store.epicgames.com/p/fixture"
        hidden = SimpleNamespace(is_visible=AsyncMock(return_value=False))
        driver.page.get_by_text = lambda *a, **kw: hidden
        driver.page.locator = lambda selector: SimpleNamespace(
            is_visible=AsyncMock(return_value=False), count=AsyncMock(
                return_value=1 if selector == 'egs-navigation[isloggedin="false"]' else 0))
        link = SimpleNamespace(is_visible=AsyncMock(return_value=True),
            get_attribute=AsyncMock(return_value="/login?redirectTo=%2Fp%2Ffixture"), click=AsyncMock())
        driver.page.get_by_role = lambda role, **kw: SimpleNamespace(
            count=AsyncMock(return_value=1 if role == "link" else 0), nth=lambda _: link)
        auth = Login(driver, {"email": "fixture@example.invalid", "password": "fixture"})
        obstacle = Obstacle("login", driver.page.url, "fixture", "product")
        await auth.login(obstacle, timeout=10)
        with self.assertRaises(Paused): await auth.login(obstacle, timeout=10)
        link.click.assert_awaited_once()
        driver._goto.assert_not_awaited()
        driver.prepare_checkout.assert_not_awaited()
        driver.submit_once.assert_not_awaited()


class ChallengeTests(unittest.IsolatedAsyncioTestCase):
    async def test_payment_rejection_retains_its_code_without_account_or_token_fields(self):
        response = SimpleNamespace(url="https://payment-website-pci.ol.epicgames.com/v2/purchase/confirm-order?token=private-account-and-token",
            status=400, request=SimpleNamespace(resource_type="xhr"),
            body=AsyncMock(return_value=json.dumps({"errorCode": "errors.com.epicgames.fixture",
                "numericErrorCode": 1001, "errorMessage": "private-account-and-token",
                "token": "private-account-and-token"}).encode()))
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            await report_purchase_error(response)
        self.assertEqual(json.loads(stream.getvalue()), {"event": "epic_purchase_error",
            "status": 400, "operation": "confirm-order",
            "error_code": "errors.com.epicgames.fixture", "numeric_code": 1001})
        self.assertNotIn("private-account", stream.getvalue())

    async def test_late_handler_receives_the_original_puzzle_once_and_ignores_preflights(self):
        received = []
        page = SimpleNamespace(on=lambda event, callback: setattr(page, "response", callback))
        def response(path, method, status=200, host="api.hcaptcha.com"):
            return SimpleNamespace(url="https://" + host + path, status=status,
                                   request=SimpleNamespace(method=method))
        script = response("/asset/hsw.js", "GET", host="newassets.hcaptcha.com")
        payload = response("/getcaptcha/fixture", "POST")
        preflight = response("/getcaptcha/fixture", "OPTIONS")
        class Agent(FixtureAgent):
            def __init__(self, page, **kwargs):
                super().__init__(**kwargs)
                page.on("response", self._task_handler)
            async def _task_handler(self, response): received.append(response)
            async def wait_for_challenge(self):
                self.assert_puzzle()
                return SimpleNamespace(value="success")
            def assert_puzzle(self):
                if received[:2] != [script, payload]: raise ValueError("missing_original_puzzle")
        handler = HCaptchaHandler(page, None, loader=lambda _: SimpleNamespace(AgentV=Agent),
                                  initial_responses=[script, preflight, payload])
        obstacle = Obstacle("captcha", "fixture", fingerprint("x"), "checkout")
        out = await handler.handle(obstacle, timeout=1)
        self.assertEqual(received, [script, payload])
        self.assertTrue(out["requires_readback"])
        await page.response(response("/checkcaptcha/fixture", "OPTIONS"))
        await page.response(response("/checkcaptcha/fixture", "POST", host="unrelated.invalid"))
        failed = response("/checkcaptcha/fixture", "POST", status=400)
        await page.response(failed)
        await handler.handle(obstacle, timeout=1)
        self.assertEqual(received, [script, payload, failed])
        self.assertEqual(handler.initial_responses, ())

    async def test_each_new_puzzle_keeps_its_question_alongside_the_sdk_skill(self):
        prompts = []
        class Agent(FixtureAgent):
            async def wait_for_challenge(self):
                prompts.append(self.robotic_arm._match_user_prompt("point"))
                return SimpleNamespace(value="success")
        handler = HCaptchaHandler(None, None, loader=lambda _: SimpleNamespace(AgentV=Agent))
        obstacle = Obstacle("captcha", "fixture", fingerprint("x"), "checkout")
        await handler.handle(obstacle, timeout=1)
        for question in ("Click the animal the ball misses", "Select the matching shape"):
            handler.agent.robotic_arm.captcha_payload = SimpleNamespace(
                get_requester_question=lambda: question)
            await handler.handle(obstacle, timeout=1)
        self.assertEqual(prompts, ["JobType: fixture",
            "Click the animal the ball misses\nJobType: fixture",
            "Select the matching shape\nJobType: fixture"])

    async def test_managed_cloudflare_without_widget_waits_without_loading_hcaptcha(self):
        page=SimpleNamespace(frames=[],wait_for_timeout=AsyncMock())
        auth=Login(SimpleNamespace(page=page),{})
        obstacle=Obstacle("captcha","https://store.epicgames.com/free-games","fixture","session",
            {"_provider":"cloudflare","_container":page})
        with patch("platforms.epic.native.build_challenge") as factory:
            await auth.captcha(obstacle,timeout=2)
        factory.assert_not_called()
        page.wait_for_timeout.assert_awaited_once_with(2000)

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
        class Agent(FixtureAgent):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
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

        class Agent(FixtureAgent):
            def __init__(self, **kw):
                super().__init__(**kw)
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
