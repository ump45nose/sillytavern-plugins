import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from platforms.epic.gates import (
    RememberedAccountHandler,
    AccountLinkHandler,
    LicenseHandler,
    unique_visible,
)
from platforms.epic.workflow import Obstacle, Paused
from platforms.epic.obstacles import classify


class Control:
    def __init__(self, *, count=1, visible=True, enabled=True):
        self.number = count
        self.visible = visible
        self.enabled = enabled
        self.click = AsyncMock()
        self.check = AsyncMock()

    async def count(self):
        return self.number

    def nth(self, index):
        return self

    async def is_visible(self):
        return self.visible

    async def is_enabled(self):
        return self.enabled

    async def get_attribute(self, name):
        return "checkbox" if name == "type" else None


class GateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.control = Control()
        self.page = SimpleNamespace(
            url="https://www.epicgames.com/id/login",
            get_by_role=lambda *a, **kw: self.control,
            get_by_text=lambda *a, **kw: self.control,
            locator=lambda *a, **kw: self.control,
        )
        self.obstacle = Obstacle("terms", self.page.url, "f" * 64, "session")

    async def test_ambiguous_control_not_clicked(self):
        self.control.number = 2
        with self.assertRaises(Paused):
            await unique_visible(self.control)
        self.control.click.assert_not_called()

    async def test_remembered_account_is_consent_bearing_login(self):
        state = classify(
            {"remembered_account": True},
            phase="session",
            target=self.page.url,
            evidence_fingerprint="f" * 64,
        )
        self.assertEqual(state.kind, "login")
        handler = RememberedAccountHandler(self.page, "owner@example.invalid")
        out = await handler(state, timeout=5)
        self.assertTrue(out["requires_readback"])
        self.control.click.assert_awaited_once()

    async def test_remembered_account_not_first_arbitrary_button(self):
        queried = []

        def text(value, **kwargs):
            queried.append((value, kwargs))
            return self.control

        self.page.get_by_text = text
        state = Obstacle(
            "login",
            self.page.url,
            "f" * 64,
            "session",
            {"subtype": "remembered_account"},
        )
        await RememberedAccountHandler(self.page, "owner@example.invalid")(
            state, timeout=5
        )
        self.assertIn(("owner@example.invalid", {"exact": True}), queried)

    async def test_wrong_account_link_obstacle_not_clicked(self):
        with self.assertRaises(Paused):
            await AccountLinkHandler(self.page)(self.obstacle, timeout=5)
        self.control.click.assert_not_called()

    async def test_account_link_explicit_handler(self):
        state = Obstacle("account_link", self.page.url, "f" * 64, "session")
        await AccountLinkHandler(self.page)(state, timeout=5)
        self.control.click.assert_awaited_once()

    async def test_external_origin_not_clicked(self):
        self.page.url = "https://epicgames.com.attacker.invalid/login"
        state = Obstacle("account_link", self.page.url, "f" * 64, "session")
        with self.assertRaises(Paused):
            await AccountLinkHandler(self.page)(state, timeout=5)
        self.control.click.assert_not_called()

    async def test_license_requires_disclosed_exact_agreement(self):
        disclosure = AsyncMock(
            return_value={
                "fingerprint": "f" * 64,
                "agreement_links": ["https://www.epicgames.com/site/en-US/tos"],
            }
        )
        out = await LicenseHandler(self.page, disclosure)(self.obstacle, timeout=5)
        self.control.check.assert_awaited_once()
        self.control.click.assert_awaited_once()
        self.assertTrue(out["acceptance_attempted"])
        self.assertTrue(out["requires_readback"])

    async def test_changed_terms_no_check_or_accept(self):
        disclosure = AsyncMock(
            return_value={
                "fingerprint": "a" * 64,
                "agreement_links": ["https://www.epicgames.com/site/en-US/tos"],
            }
        )
        with self.assertRaises(Paused):
            await LicenseHandler(self.page, disclosure)(self.obstacle, timeout=5)
        self.control.check.assert_not_called()
        self.control.click.assert_not_called()

    async def test_missing_agreement_link_no_accept(self):
        disclosure = AsyncMock(
            return_value={"fingerprint": "f" * 64, "agreement_links": []}
        )
        with self.assertRaises(Paused):
            await LicenseHandler(self.page, disclosure)(self.obstacle, timeout=5)
        self.control.click.assert_not_called()

    async def test_privacy_correction_is_distinct_form(self):
        self.page.url = "https://www.epicgames.com/id/login/correction/privacy-policy"
        with self.assertRaises(Paused):
            await LicenseHandler(self.page, AsyncMock())(self.obstacle, timeout=5)
        self.control.check.assert_not_called()

    async def test_disabled_accept_no_click(self):
        self.control.enabled = False
        disclosure = AsyncMock(
            return_value={
                "fingerprint": "f" * 64,
                "agreement_links": ["https://www.epicgames.com/site/en-US/tos"],
            }
        )
        with self.assertRaises(Paused):
            await LicenseHandler(self.page, disclosure)(self.obstacle, timeout=5)
        self.control.click.assert_not_called()

    async def test_license_uses_observed_checkout_frame_not_outer_page(self):
        frame_control = Control()
        frame = SimpleNamespace(
            url="https://www.epicgames.com/purchase",
            locator=lambda *a: frame_control,
            get_by_role=lambda *a, **kw: frame_control,
        )
        self.page.frames = [frame]
        state = Obstacle(
            "terms",
            frame.url,
            "f" * 64,
            "checkout",
            {"subtype": "new_terms", "_container": frame},
        )
        disclosure = AsyncMock(
            return_value={
                "fingerprint": "f" * 64,
                "agreement_links": ["https://www.epicgames.com/site/en-US/tos"],
            }
        )
        await LicenseHandler(self.page, disclosure)(state, timeout=5)
        self.assertIs(disclosure.await_args.args[0], frame)
        frame_control.check.assert_awaited_once()
        frame_control.click.assert_awaited_once()
        self.control.click.assert_not_awaited()

    async def test_detached_checkout_frame_cannot_receive_approved_action(self):
        frame = SimpleNamespace(url="https://www.epicgames.com/purchase")
        self.page.frames = []
        state = Obstacle(
            "terms", frame.url, "f" * 64, "checkout", {"_container": frame}
        )
        disclosure = AsyncMock()
        with self.assertRaises(Paused):
            await LicenseHandler(self.page, disclosure)(state, timeout=5)
        disclosure.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
