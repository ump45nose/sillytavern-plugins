"""Offline Rainyun behavior checks: no account, browser or network required."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from platforms.rainyun.adapter import RainyunError, execute, load_config
from platforms.rainyun.browser import Browser, checkin_state, click_offsets, points, verify_runtime
from platforms.rainyun.run import TASK
from platforms.rainyun.state import Journal

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = {"run_id": "rainyun-test", "platform": "rainyun", "account": "account1",
           "business_date": "2026-10-19"}


class FakeBrowser:
    def __init__(self, observations, *, claim_error=None, fail_before_intent=False):
        self.observations = list(observations)
        self.claim_error = claim_error
        self.fail_before_intent = fail_before_intent
        self.claims = self.clicks = self.reads = 0
        self.before_click = None

    def open(self):
        pass

    def read(self):
        self.reads += 1
        value = self.observations.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def claim(self, before_submit):
        self.claims += 1
        if self.fail_before_intent:
            raise RainyunError("page_structure_unknown")
        before_submit()
        if self.before_click:
            self.before_click()
        self.clicks += 1
        if self.claim_error:
            raise self.claim_error


def observation(state="incomplete", balance=100):
    return {"checkin": state, "balance": balance}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.journal = Journal(CONTEXT, self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, browser, **kwargs):
        return execute(CONTEXT, browser, self.journal, **kwargs)

    def test_already_signed_is_read_only(self):
        browser = FakeBrowser([observation("complete", 200)])
        row = self.invoke(browser)
        self.assertEqual(browser.claims, 0)
        self.assertEqual(row["business"], {"checkin": "complete", "balance": "complete"})
        self.assertEqual(row["details"]["metrics"]["balance"]["delta"], 0)

    def test_claim_intent_is_durable_before_click(self):
        browser = FakeBrowser([observation(), observation("complete", 120)])
        def before_click():
            stored = json.loads(self.journal.path.read_text())
            self.assertEqual(stored["status"], "pending")
        browser.before_click = before_click
        row = self.invoke(browser)
        self.assertEqual(browser.clicks, 1)
        self.assertEqual(row["reason"], "checkin_confirmed")
        self.assertEqual(row["details"]["metrics"]["balance"]["delta"], 20)
        self.assertEqual(self.journal.status, "complete")

    def test_click_transport_error_reconciles_without_retry(self):
        browser = FakeBrowser([observation(), observation("complete", 120)],
                              claim_error=ConnectionError("sensitive exception omitted"))
        row = self.invoke(browser)
        self.assertEqual(row["reason"], "checkin_confirmed")
        self.assertEqual(browser.clicks, 1)
        self.assertEqual(browser.reads, 2)
        self.assertNotIn("sensitive", json.dumps(row))

    def test_readback_failure_keeps_before_and_unknown_after(self):
        browser = FakeBrowser([observation(balance=90), ConnectionError()])
        row = self.invoke(browser)
        metric = row["details"]["metrics"]["balance"]
        self.assertEqual(metric["current"], 90)
        self.assertEqual(metric["before"], 90)
        self.assertIsNone(metric["after"])
        self.assertIsNone(metric["delta"])
        self.assertEqual(row["business"]["checkin"], "unknown")
        self.assertEqual(Journal(CONTEXT, self.directory).status, "pending")

    def test_new_process_pending_never_claims_again(self):
        self.journal.set("pending")
        journal = Journal(CONTEXT, self.directory)
        browser = FakeBrowser([observation()])
        row = execute(CONTEXT, browser, journal)
        self.assertEqual(browser.claims, 0)
        self.assertEqual(row["reason"], "claim_pending_readback")
        self.assertEqual(row["business"]["checkin"], "unknown")

    def test_pending_can_be_confirmed_by_readback(self):
        self.journal.set("pending")
        browser = FakeBrowser([observation("complete")])
        self.assertEqual(self.invoke(browser)["business"]["checkin"], "complete")
        self.assertEqual(browser.claims, 0)
        self.assertEqual(self.journal.status, "complete")

    def test_previous_confirmation_is_not_replayed_when_page_disagrees(self):
        self.journal.set("complete")
        browser = FakeBrowser([observation()])
        row = self.invoke(browser)
        self.assertEqual(browser.claims, 0)
        self.assertEqual(row["reason"], "checkin_state_conflict")

    def test_unknown_button_never_claims_or_reports_success(self):
        browser = FakeBrowser([observation("unknown")])
        row = self.invoke(browser)
        self.assertEqual(browser.claims, 0)
        self.assertEqual(row["business"]["checkin"], "unknown")

    def test_failed_captcha_does_not_complete_checkin(self):
        browser = FakeBrowser([observation(), observation()],
                              claim_error=RainyunError("captcha_unconfirmed"))
        row = self.invoke(browser)
        self.assertEqual(browser.clicks, 1)
        self.assertEqual(row["business"]["checkin"], "blocked")
        self.assertEqual(row["reason"], "captcha_unconfirmed")

    def test_read_only_mode_has_no_intent(self):
        browser = FakeBrowser([observation()])
        row = self.invoke(browser, read_only=True)
        self.assertEqual(row["reason"], "status_only")
        self.assertEqual(browser.claims, 0)
        self.assertFalse(self.journal.path.exists())

    def test_failure_before_click_does_not_create_pending(self):
        browser = FakeBrowser([observation(), observation()], fail_before_intent=True)
        self.invoke(browser)
        self.assertEqual(self.journal.status, "unknown")
        self.assertFalse(self.journal.path.exists())

    def test_balance_failure_does_not_revoke_confirmed_checkin(self):
        browser = FakeBrowser([observation(), observation("complete", None)])
        row = self.invoke(browser)
        self.assertEqual(row["business"]["checkin"], "complete")
        self.assertEqual(row["business"]["balance"], "unknown")
        self.assertIsNone(row["details"]["metrics"]["balance"]["delta"])

    def test_next_day_gets_a_new_intent(self):
        self.journal.set("pending")
        tomorrow = {**CONTEXT, "business_date": "2026-10-20"}
        self.assertEqual(Journal(tomorrow, self.directory).status, "unknown")

    def test_invalid_journal_is_visible(self):
        self.journal.path.write_text('{"status":"complete"}')
        with self.assertRaises(ValueError):
            Journal(CONTEXT, self.directory)


class ParsingTests(unittest.TestCase):
    def test_only_exact_completion_is_success(self):
        self.assertEqual(checkin_state(" 已完成 "), "complete")
        self.assertEqual(checkin_state("领取奖励"), "incomplete")
        for text in ("", "...", "加载中", "领取中", "已完成 0/1", "签到成功？"):
            self.assertEqual(checkin_state(text), "unknown")

    def test_points_not_digits_joined_from_arbitrary_text(self):
        self.assertEqual(points("1,234"), 1234)
        self.assertEqual(points("0"), 0)
        self.assertEqual(points("12.5"), 12.5)
        for text in ("余额 1 奖励 20", "12,34", "NaN", "-1", "", "999999999999999"):
            self.assertIsNone(points(text))

    def test_captcha_coordinates_preserve_sprite_order_and_scale(self):
        matches = [{"sprite_idx": i, "bg_rect": [i * 60 + 10, 20, 20, 20]}
                   for i in (2, 0, 1)]
        self.assertEqual(click_offsets(matches, (200, 100), (400, 200)),
                         [(-160, -40), (-40, -40), (80, -40)])

    def test_invalid_captcha_matches_never_click(self):
        good = [{"sprite_idx": i, "bg_rect": [10 + i * 40, 10, 20, 20]} for i in range(3)]
        cases = [[], good[:2], [good[0]] * 3,
                 [{"sprite_idx": i, "bg_rect": [1000, 10, 20, 20]} for i in range(3)]]
        for matches in cases:
            with self.assertRaises(RainyunError):
                click_offsets(matches, (200, 100), (400, 200))


class CaptchaTests(unittest.TestCase):
    class Timeout(Exception):
        pass

    class DriverError(Exception):
        pass

    def setUp(self):
        self.browser = Browser({}, "/tmp/not-created")
        self.browser.sleep = lambda _: None
        self.browser.driver = MagicMock()
        self.browser.Timeout, self.browser.WebDriverError = self.Timeout, self.DriverError
        self.elements = {}
        for selector in ("#slideBg", "#instruction div img", "#reload", "#tcOperation"):
            element = MagicMock()
            element.is_displayed.return_value = True
            element.is_enabled.return_value = True
            self.elements[selector] = element
        background = self.elements["#slideBg"]
        background.get_attribute.return_value = 'background-image: url("https://t.captcha.qq.com/bg");'
        background.rect = {"width": 200, "height": 100}
        self.confirm = MagicMock()
        self.confirm.is_displayed.return_value = self.confirm.is_enabled.return_value = True
        from platforms.rainyun.browser import CONFIRM_CAPTCHA
        self.elements[CONFIRM_CAPTCHA] = self.confirm
        self.browser.driver.find_elements.side_effect = lambda kind, selector: (
            [self.elements[selector]] if selector in self.elements else [])
        self.browser._image = lambda _: b"image bytes"
        self.browser.recognize = lambda *_: [
            {"sprite_idx": i, "bg_rect": [10 + i * 40, 10, 20, 20]} for i in range(3)]
        self.browser.Actions = MagicMock()
        timeout = self.Timeout
        class ImmediateWait:
            def __init__(self, *args, **kwargs):
                pass
            def until(self, predicate):
                value = predicate(None)
                if not value:
                    raise timeout()
                return value
        self.browser.Wait = ImmediateWait
        self.modules = patch.dict(sys.modules, {
            "cv2": SimpleNamespace(imdecode=lambda *_: SimpleNamespace(shape=(100, 200, 3)), IMREAD_COLOR=1),
            "numpy": SimpleNamespace(frombuffer=lambda *_args, **_kwargs: b"decoded", uint8=1),
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def test_unknown_submission_outcome_is_not_retried(self):
        self.elements["#tcOperation"].get_attribute.return_value = "tc-opera pointer"
        with self.assertRaisesRegex(RainyunError, "captcha_unconfirmed"):
            self.browser._solve_captcha(MagicMock())
        self.assertEqual(self.confirm.click.call_count, 1)
        self.assertEqual(self.elements["#reload"].click.call_count, 0)
        self.browser.driver.switch_to.default_content.assert_called_once()

    def test_explicit_rejection_allows_one_refresh(self):
        self.elements["#tcOperation"].get_attribute.side_effect = ["tc-opera show-error", "tc-opera show-success"]
        self.browser._solve_captcha(MagicMock())
        self.assertEqual(self.confirm.click.call_count, 2)
        self.assertEqual(self.elements["#reload"].click.call_count, 1)
        self.assertEqual(self.browser.captcha_attempts, 2)

    def test_recognition_failure_is_bounded_before_any_submission(self):
        self.browser.recognize = lambda *_: []
        with self.assertRaisesRegex(RainyunError, "captcha_recognition_failed"):
            self.browser._solve_captcha(MagicMock())
        self.assertEqual(self.confirm.click.call_count, 0)
        self.assertEqual(self.elements["#reload"].click.call_count, 1)
        self.assertEqual(self.browser.captcha_attempts, 2)


class ConfigurationTests(unittest.TestCase):
    def test_private_config_required_and_proxy_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            value = {"username": "fixture", "password": "fixture", "chromium_path": "/a/chrome",
                     "chromedriver_path": "/a/chromedriver", "provider_root": "/a/provider"}
            path.write_text(json.dumps(value))
            path.chmod(0o600)
            self.assertEqual(load_config(str(path))["username"], "fixture")
            value["proxy"] = "http://127.0.0.1:7890"
            path.write_text(json.dumps(value))
            self.assertEqual(load_config(str(path))["proxy"], value["proxy"])
            value["proxy"] = "http://user:password@proxy.example:8080"
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(RainyunError, "invalid_proxy"):
                load_config(str(path))
            path.chmod(0o644)
            with self.assertRaisesRegex(RainyunError, "private_file_permissions"):
                load_config(str(path))

    def test_version_mismatch_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "binary"
            path.write_text("unused")
            path.chmod(0o700)
            config = {"chromium_path": str(path), "chromedriver_path": str(path)}
            with patch("platforms.rainyun.browser.subprocess.check_output", return_value="Chrome 1.2.3.4"):
                with self.assertRaisesRegex(RainyunError, "browser_version_mismatch"):
                    verify_runtime(config)

    def test_browser_and_provider_deps_not_loaded_for_offline_entry(self):
        with tempfile.TemporaryDirectory() as root:
            child = subprocess.run([sys.executable, str(ROOT / "platforms/rainyun/run.py"),
                                    "--runtime-root", root],
                                   env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=5)
            self.assertEqual(child.returncode, 1)
            self.assertEqual(json.loads(child.stdout)["reason"], "execution_not_requested")
            self.assertFalse((Path(root) / "results").exists())
        self.assertTrue(TASK.browser)
        self.assertEqual(TASK.environment, frozenset(["RAINYUN_CONFIG"]))

    def test_missing_configuration_is_structured_and_does_not_launch_browser(self):
        with tempfile.TemporaryDirectory() as root:
            child = subprocess.run([sys.executable, str(ROOT / "platforms/rainyun/run.py"),
                                    "--runtime-root", root, "--execute"],
                                   env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=5)
            self.assertEqual(child.returncode, 1)
            self.assertEqual(json.loads(child.stdout)["reason"], "missing_configuration")

    def test_unexpected_image_host_is_rejected_before_request(self):
        browser = Browser({}, "/tmp/not-created")
        browser.driver = MagicMock()
        with self.assertRaisesRegex(RainyunError, "captcha_image_origin_unknown"):
            browser._image("http://127.0.0.1/private")
        browser.driver.execute_script.assert_not_called()


if __name__ == "__main__":
    unittest.main()
