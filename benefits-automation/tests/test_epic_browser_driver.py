import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from platforms.epic.browser_driver import BrowserDriver, clean_target
from platforms.epic.workflow import Paused, Obstacle
from platforms.epic.native import checkout_evidence


class OriginTests(unittest.TestCase):
    def test_clean_origin(self):
        self.assertEqual(
            clean_target("https://store.epicgames.com/en-US/cart?token=fixture#secret"),
            "https://store.epicgames.com/en-US/cart",
        )

    def test_reject_external(self):
        for url in (
            "http://store.epicgames.com",
            "https://store.epicgames.com.evil.invalid",
            "https://x@store.epicgames.com",
            "https://store.epicgames.com:444",
        ):
            with self.assertRaises(Paused):
                clean_target(url)


class CheckoutIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_single_offer_purchase_identity(self):
        ns, oid = "a" * 32, "b" * 32
        frame = SimpleNamespace(url=f"https://store.epicgames.com/purchase?offers=1-{ns}-{oid}--")
        self.assertEqual(await checkout_evidence(frame, timeout=1),
            {"complete": True, "offer_ids": [f"{ns}:{oid}"]})

    async def test_ambiguous_or_unobserved_purchase_formats_remain_unknown(self):
        ns, oid = "a" * 32, "b" * 32
        for query in (
            f"offers=1-{ns}-{oid}--&offers=1-{ns}-{'c'*32}--",
            f"offers=2-{ns}-{oid}--", f"offers=1-{ns}-{oid}--extra",
            f"offers=1-{ns}-{oid}--&namespace={'c'*32}",
        ):
            with self.subTest(query=query):
                frame = SimpleNamespace(url="https://store.epicgames.com/purchase?" + query)
                self.assertEqual(await checkout_evidence(frame, timeout=1), {"complete": False})


class Controls:
    async def count(self):
        return 1

    def nth(self, index):
        return self

    async def is_visible(self):
        return True


class DriverTests(unittest.IsolatedAsyncioTestCase):
    async def test_denied_assets_report_when_bounded_business_observation_stays_unknown(self):
        driver = BrowserDriver(None, None, None)
        driver.observe_asset_response(SimpleNamespace(
            url="https://store.epicgames.com/egs-v2/assets/fixture.js", status=403))
        driver._observe_once = AsyncMock(return_value=SimpleNamespace(kind="unknown"))
        driver._purchase_controls = lambda _: SimpleNamespace(first=SimpleNamespace(wait_for=AsyncMock()))
        with patch("platforms.epic.browser_driver.asyncio.sleep", new=AsyncMock()), self.assertRaises(Paused) as raised:
            await driver.observe("product", timeout=10)
        self.assertEqual(raised.exception.reason, "store_assets_access_denied")
        self.assertEqual(driver._observe_once.await_count, 8)

    async def test_optional_asset_denial_cannot_mask_working_controls_or_a_real_obstacle(self):
        for state in [None, SimpleNamespace(kind="login"), SimpleNamespace(kind="captcha")]:
            driver = BrowserDriver(None, None, None)
            driver.assets_denied = True
            driver._observe_once = AsyncMock(return_value=state)
            self.assertIs(await driver.observe("product", timeout=1), state)
            driver._observe_once.assert_awaited_once()

    async def test_store_login_transition_uses_only_the_explicit_sso_binding(self):
        page = SimpleNamespace(url="https://store.epicgames.com/login?redirectTo=fixture",
            locator=lambda _: object(), get_by_role=lambda *a, **kw: object())
        callback = AsyncMock()
        driver = BrowserDriver(None, page, None, sso_login=callback)
        driver._text = AsyncMock(return_value="Loading")
        driver._visible = AsyncMock(return_value=False)
        driver._ready = AsyncMock(return_value=False)
        obstacle = await driver._observe_container(page, "checkout", timeout=1)
        self.assertEqual(obstacle.kind, "store_sso")
        self.assertIs(obstacle.payload["_container"], page)
        await driver.recover(obstacle, timeout=1)
        callback.assert_awaited_once_with(obstacle, timeout=1)

    async def test_navigation_timeout_accepts_the_canonical_page_with_its_navigation_component(self):
        try:
            from playwright.async_api import TimeoutError as BrowserTimeout
        except ImportError:
            self.skipTest("optional browser dependency unavailable")
        page = SimpleNamespace(url="https://store.epicgames.com/free-games",
            goto=AsyncMock(side_effect=BrowserTimeout("fixture")),
            locator=lambda _: SimpleNamespace(count=AsyncMock(return_value=1)))
        driver = BrowserDriver(None, page, None)
        await driver._goto("https://store.epicgames.com/en-US/free-games", 1)
        page.goto.assert_awaited_once()
        page.url = "https://store.epicgames.com/p/unrelated"
        with self.assertRaises(BrowserTimeout):
            await driver._goto("https://store.epicgames.com/en-US/free-games", 1)
        page.url = "about:blank"
        with self.assertRaises(BrowserTimeout):
            await driver._goto("https://store.epicgames.com/en-US/free-games", 1)

    async def test_navigation_does_not_hide_other_browser_errors_behind_existing_dom(self):
        page = SimpleNamespace(url="https://store.epicgames.com/free-games",
            goto=AsyncMock(side_effect=RuntimeError("protocol failure")),
            locator=lambda _: SimpleNamespace(count=AsyncMock(return_value=1)))
        with self.assertRaises(RuntimeError):
            await BrowserDriver(None, page, None)._goto(page.url, 1)

    async def test_denied_optional_assets_do_not_replace_current_ownership_markers(self):
        page = SimpleNamespace(url="https://store.epicgames.com/p/fixture")
        driver = BrowserDriver(None, page, None)
        driver.assets_denied = True
        driver._purchase_controls = lambda _: SimpleNamespace(first=SimpleNamespace(wait_for=AsyncMock()))
        button = object()
        driver._purchase_button = AsyncMock(return_value=button)
        for text, expected in [("In Library", "owned"), ("Get", "not_owned")]:
            driver._purchase_text = AsyncMock(return_value=text)
            self.assertEqual(await driver._ownership(page, SimpleNamespace(url=page.url), timeout=1), expected)

    async def test_unrelated_tracking_failure_does_not_block_the_product(self):
        driver = BrowserDriver(None, None, None)
        for url, status in [("https://tracking.epicgames.com/track.png", 403),
                            ("https://store.epicgames.com/egs-v2/assets/fixture.js", 200)]:
            driver.observe_asset_response(SimpleNamespace(url=url, status=status))
        self.assertFalse(driver.assets_denied)

    async def test_current_device_warning_continues_once_to_the_price_gate(self):
        button = SimpleNamespace(count=AsyncMock(return_value=1), is_visible=AsyncMock(return_value=True),
            is_enabled=AsyncMock(return_value=True), click=AsyncMock())
        dialog = SimpleNamespace(count=AsyncMock(return_value=1), is_visible=AsyncMock(return_value=True),
            inner_text=AsyncMock(return_value="Device not supported\nThis product is not compatible with your current device\nCancel\nContinue"),
            get_by_role=lambda *a, **k: button, wait_for=AsyncMock())
        page = SimpleNamespace(url="https://store.epicgames.com/p/fixture",get_by_role=lambda *a, **k: dialog)
        driver = BrowserDriver(None,page,None)
        driver.offer = SimpleNamespace(id="fixture")
        driver.prepared.add("fixture")
        obstacle = Obstacle("region_layout",page.url,"fixture","checkout",
            {"subtype":"device_modal","_container":page})
        await driver.recover(obstacle,timeout=10)
        button.click.assert_awaited_once()
        self.assertIsNone(driver.checkout_button)
        with self.assertRaises(Paused): await driver.recover(obstacle,timeout=10)
        self.assertEqual(button.click.await_count,1)
        dialog.inner_text.return_value += "\nAccept new terms"
        driver.device_acknowledged.clear()
        with self.assertRaises(Paused): await driver.recover(obstacle,timeout=10)
        self.assertEqual(button.click.await_count,1)

    async def test_checkout_hydration_waits_beyond_the_product_window(self):
        driver = BrowserDriver(None, None, None)
        unknown = SimpleNamespace(kind="unknown")
        driver._observe_once = AsyncMock(side_effect=[unknown] * 12 + [None])
        with patch("platforms.epic.browser_driver.asyncio.sleep", new=AsyncMock()):
            self.assertIsNone(await driver.observe("checkout", timeout=30))
        self.assertEqual(driver._observe_once.await_count, 13)

    async def test_visibility_without_deprecated_timeout(self):
        d = BrowserDriver(None, None, None)
        self.assertTrue(await d._visible(Controls()))

    async def test_hidden_first_frame_does_not_hide_visible_challenge(self):
        class Element:
            def __init__(self, visible):
                self.visible = visible

            async def is_visible(self, **kw):
                return self.visible

        class Frames:
            async def count(self):
                return 2

            def nth(self, index):
                return Element(index == 1)

        d = BrowserDriver(None, None, None)
        self.assertTrue(await d._visible(Frames()))

    async def test_excessive_observation_matches_are_not_silently_ignored(self):
        class Frames:
            async def count(self):
                return 33

        d = BrowserDriver(None, None, None)
        with self.assertRaises(Paused):
            await d._visible(Frames())

    async def test_observed_chinese_security_gate_is_challenge(self):
        page = SimpleNamespace(
            url="https://store.epicgames.com/en-US/free-games",
            frames=[],
            locator=lambda *a: object(),
            get_by_role=lambda *a, **kw: object(),
        )
        d = BrowserDriver(None, page, None)

        async def hidden(*a, **kw):
            return False

        async def text(*a, **kw):
            return "再进行一步操作\n请完成安全检查以继续"

        d._visible = hidden
        d._text = text
        d._captcha_evidence = AsyncMock(return_value=["fixture-pixels"])
        state = await d.observe("session", timeout=1)
        self.assertEqual(state.kind, "captcha")

    async def test_main_frame_not_counted_twice(self):
        frame = SimpleNamespace(url="https://store.epicgames.com/en-US/cart")
        page = SimpleNamespace(
            url=frame.url,
            main_frame=frame,
            frames=[frame],
            get_by_role=lambda *a, **kw: Controls(),
        )
        d = BrowserDriver(None, page, None)
        controls = await d._checkout_controls()
        self.assertEqual(len(controls), 1)

    async def test_unrecognized_cart_not_empty(self):
        class Empty:
            async def count(self):
                return 0

        page = SimpleNamespace(locator=lambda *a: Empty())
        d = BrowserDriver(None, page, None)

        async def text(*a, **kw):
            return "Loading"

        d._text = text
        self.assertEqual(await d.inspect_cart(timeout=1), "unknown")

    async def test_unknown_page_is_not_phase_ready(self):
        page = SimpleNamespace(
            url="https://store.epicgames.com/en-US/free-games",
            locator=lambda s: SimpleNamespace(count=AsyncMock(return_value=0))
            if s == 'egs-navigation[isloggedin="true"]' else s,
            get_by_role=lambda *a, **k: "button",
        )
        d = BrowserDriver(None, page, None)
        d._text = AsyncMock(return_value="Loading")
        d._visible = AsyncMock(return_value=False)
        self.assertEqual((await d.observe("session", timeout=1)).kind, "unknown")

    async def test_positive_authenticated_navigation_is_session_ready(self):
        page = SimpleNamespace(
            url="https://store.epicgames.com/en-US/free-games",
            locator=lambda s: SimpleNamespace(count=AsyncMock(return_value=1))
            if s == 'egs-navigation[isloggedin="true"]' else s,
            get_by_role=lambda *a, **k: "button",
        )
        d = BrowserDriver(None, page, None)
        d._text = AsyncMock(return_value="Store")
        d._visible = AsyncMock(
            side_effect=lambda s: s == 'egs-navigation[isloggedin="true"]'
        )
        self.assertIsNone(await d.observe("session", timeout=1))

    async def test_same_iframe_refresh_changes_pixel_fingerprint(self):
        surface = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            bounding_box=AsyncMock(return_value={"width": 300, "height": 200}),
            screenshot=AsyncMock(side_effect=[b"image-one", b"image-two"]),
        )
        frames = SimpleNamespace(count=AsyncMock(return_value=1), nth=lambda i: surface)
        page = SimpleNamespace(
            url="https://store.epicgames.com/en-US/p/fixture",
            locator=lambda s: frames if s.startswith("iframe") else s,
            get_by_role=lambda *a, **k: "button",
        )
        d = BrowserDriver(None, page, None)
        d._text = AsyncMock(return_value="verify you are human")
        d._visible = AsyncMock(return_value=False)
        first = await d.observe("product", timeout=1)
        second = await d.observe("product", timeout=1)
        self.assertEqual(first.kind, "captcha")
        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(surface.screenshot.await_count, 2)

    async def test_same_iframe_refresh_while_approval_pending_blocks_handler(self):
        from platforms.epic.workflow import ClaimWorkflow
        from common.interventions import IDENTITY

        surface = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            bounding_box=AsyncMock(return_value={"width": 300, "height": 200}),
            screenshot=AsyncMock(side_effect=[b"image-one", b"image-two"]),
        )
        frames = SimpleNamespace(count=AsyncMock(return_value=1), nth=lambda i: surface)
        page = SimpleNamespace(
            url="https://store.epicgames.com/en-US/p/fixture",
            locator=lambda s: frames if s.startswith("iframe") else s,
            get_by_role=lambda *a, **k: "button",
        )
        d = BrowserDriver(None, page, None)
        d._text = AsyncMock(return_value="verify you are human")
        d._visible = AsyncMock(return_value=False)

        async def approve(req):
            return {
                **{k: req[k] for k in IDENTITY},
                "decision": "approve",
                "expires_at": "2099-01-01T00:00:00Z",
            }

        handler = AsyncMock()
        workflow = ClaimWorkflow(
            d,
            {"run_id": "fixture", "platform": "epic", "account": "one"},
            deadline=100,
            clock=lambda: 0,
            expires_at="2099-01-01T00:00:00Z",
            approve=approve,
            handlers={"captcha": handler},
        )
        with self.assertRaises(Paused) as error:
            await workflow.settle("product")
        self.assertEqual(error.exception.reason, "site_state_changed")
        handler.assert_not_awaited()

    async def test_oversized_challenge_not_screenshotted(self):
        surface = SimpleNamespace(
            is_visible=AsyncMock(return_value=True),
            bounding_box=AsyncMock(return_value={"width": 3000, "height": 3000}),
            screenshot=AsyncMock(),
        )
        frames = SimpleNamespace(count=AsyncMock(return_value=1), nth=lambda i: surface)
        d = BrowserDriver(None, None, None)
        with self.assertRaises(Paused):
            await d._captcha_evidence(
                SimpleNamespace(locator=lambda s: frames), timeout=1
            )
        surface.screenshot.assert_not_awaited()

    async def test_checkout_frame_terms_are_observed_and_bound(self):
        frame = SimpleNamespace(
            url="https://www.epicgames.com/purchase",
            locator=lambda s: ("frame", s),
            get_by_role=lambda *a, **k: ("frame", "button"),
            frame_element=AsyncMock(
                return_value=SimpleNamespace(is_visible=AsyncMock(return_value=True))
            ),
        )
        page = SimpleNamespace(
            url="https://store.epicgames.com/en-US/p/fixture",
            main_frame=object(),
            frames=[frame],
            locator=lambda s: ("page", s),
            get_by_role=lambda *a, **k: ("page", "button"),
        )
        d = BrowserDriver(None, page, None)
        d._text = AsyncMock(return_value="License terms")
        d._visible = AsyncMock(
            side_effect=lambda s: s == ("frame", 'label[for="agree"]')
        )
        d._checkout_controls = AsyncMock(return_value=[])
        state = await d.observe("checkout", timeout=1)
        self.assertEqual(state.kind, "terms")
        self.assertIs(state.payload["_container"], frame)
        self.assertEqual(state.target, frame.url)

    async def test_readonly_verification_closes_separate_page(self):
        from platforms.epic.workflow import Offer

        offer = Offer("a", "https://store.epicgames.com/en-US/p/fixture", True)
        button = SimpleNamespace(inner_text=AsyncMock(return_value="In Library"), wait_for=AsyncMock(),
            is_visible=AsyncMock(return_value=True))
        controls = SimpleNamespace(first=button, count=AsyncMock(return_value=1), nth=lambda i: button)
        verification = SimpleNamespace(
            url=offer.url,
            goto=AsyncMock(),
            close=AsyncMock(),
            get_by_role=lambda *a, **k: controls,
        )
        checkout = SimpleNamespace(goto=AsyncMock())
        context = SimpleNamespace(new_page=AsyncMock(return_value=verification))
        d = BrowserDriver(context, checkout, None)
        d._visible = AsyncMock(return_value=True)
        self.assertEqual(await d.verify_readonly(offer, timeout=1), "owned")
        checkout.goto.assert_not_awaited()
        verification.close.assert_awaited_once()

    async def test_readonly_timeout_closes_page_without_leaving_checkout(self):
        from platforms.epic.workflow import Offer

        offer = Offer("a", "https://store.epicgames.com/en-US/p/fixture", True)
        verification = SimpleNamespace(
            goto=AsyncMock(side_effect=TimeoutError()), close=AsyncMock()
        )
        checkout = SimpleNamespace(goto=AsyncMock())
        d = BrowserDriver(
            SimpleNamespace(new_page=AsyncMock(return_value=verification)),
            checkout,
            None,
        )
        with self.assertRaises(TimeoutError):
            await d.verify_readonly(offer, timeout=1)
        checkout.goto.assert_not_awaited()
        verification.close.assert_awaited_once()

    async def test_real_playwright_timeout_retries_readback_then_preserves_gate(self):
        try:
            from playwright.async_api import TimeoutError as BrowserTimeoutError
        except ImportError:
            self.skipTest("optional Playwright dependency is not installed")
        from platforms.epic.workflow import ClaimWorkflow, Obstacle, Offer
        from common.interventions import fingerprint

        offer = Offer("a", "https://store.epicgames.com/en-US/p/fixture", True)
        readback_pages = [
            SimpleNamespace(
                goto=AsyncMock(side_effect=BrowserTimeoutError("fixture navigation")),
                close=AsyncMock(),
            )
            for _ in range(3)
        ]
        context = SimpleNamespace(new_page=AsyncMock(side_effect=readback_pages))
        journal = SimpleNamespace(read=AsyncMock(return_value=None), write=AsyncMock())
        d = BrowserDriver(context, object(), journal)
        d.observe = AsyncMock(
            side_effect=[
                None,
                None,
                None,
                None,
                Obstacle("captcha", offer.url, fingerprint("late"), "post_submit"),
            ]
        )
        d.inventory = AsyncMock(return_value=[offer])
        d.open_offer = AsyncMock()
        d.verify = AsyncMock(return_value="not_owned")
        d.prepare_cart = AsyncMock()
        d.checkout_uses_cart = AsyncMock(return_value=True)
        d.inspect_cart = AsyncMock(return_value="empty_confirmed")
        d.prepare_checkout = AsyncMock()
        d.checkout_total = AsyncMock(return_value="explicit_zero")
        d.submit_once = AsyncMock()
        result = await ClaimWorkflow(
            d,
            {"run_id": "fixture", "platform": "epic", "account": "one"},
            deadline=100,
            clock=lambda: 0,
            expires_at="2099-01-01T00:00:00Z",
            readback_interval=0,
            sleep=AsyncMock(),
        ).run()
        self.assertEqual(result.reason, "approval_or_handler_needed")
        self.assertEqual(result.uncertain, ["a"])
        self.assertEqual(result.pending[0]["phase"], "post_submit")
        self.assertEqual(context.new_page.await_count, 3)
        d.submit_once.assert_awaited_once()
        for page in readback_pages:
            page.close.assert_awaited_once()

    async def test_real_playwright_ownership_timeout_is_normalized(self):
        try:
            from playwright.async_api import TimeoutError as BrowserTimeoutError
        except ImportError:
            self.skipTest("optional Playwright dependency is not installed")
        from platforms.epic.workflow import Offer

        offer = Offer("a", "https://store.epicgames.com/en-US/p/fixture", True)
        verification = SimpleNamespace(goto=AsyncMock(), close=AsyncMock())
        d = BrowserDriver(
            SimpleNamespace(new_page=AsyncMock(return_value=verification)),
            object(),
            None,
        )
        d._ownership = AsyncMock(side_effect=BrowserTimeoutError("fixture ownership"))
        with self.assertRaises(TimeoutError):
            await d.verify_readonly(offer, timeout=1)
        verification.close.assert_awaited_once()

    async def test_readonly_deterministic_and_authorization_errors_are_not_normalized(
        self,
    ):
        from platforms.epic.workflow import Offer

        try:
            from playwright.async_api import Error as BrowserError
        except ImportError:
            self.skipTest("optional Playwright dependency is not installed")

        offer = Offer("a", "https://store.epicgames.com/en-US/p/fixture", True)
        for original in [
            BrowserError("strict mode violation"),
            Paused("unexpected_origin"),
        ]:
            verification = SimpleNamespace(goto=AsyncMock(), close=AsyncMock())
            d = BrowserDriver(
                SimpleNamespace(new_page=AsyncMock(return_value=verification)),
                object(),
                None,
            )
            d._ownership = AsyncMock(side_effect=original)
            with self.assertRaises(type(original)) as raised:
                await d.verify_readonly(offer, timeout=1)
            self.assertIs(raised.exception, original)
            verification.close.assert_awaited_once()

    async def test_empty_cart_requires_positive_marker(self):
        class Empty:
            async def count(self):
                return 0

        d = BrowserDriver(None, SimpleNamespace(locator=lambda *a: Empty()), None)

        async def text(*a, **kw):
            return "Your cart is empty"

        d._text = text
        self.assertEqual(await d.inspect_cart(timeout=1), "empty_confirmed")

    async def test_submit_without_verified_zero_never_clicks(self):
        d = BrowserDriver(None, None, None)
        with self.assertRaises(Paused):
            await d.submit_once(None, timeout=1)

    async def test_text_overflow_not_truncated_price(self):
        class Body:
            async def evaluate(self, *args):
                return None

        d = BrowserDriver(None, SimpleNamespace(locator=lambda *a: Body()), None)
        with self.assertRaises(Paused):
            await d._text()

    async def test_extra_order_controls_are_not_ignored(self):
        class Many(Controls):
            async def count(self):
                return 9

        frame = SimpleNamespace(url="https://store.epicgames.com/en-US/cart")
        page = SimpleNamespace(
            url=frame.url,
            main_frame=frame,
            frames=[frame],
            get_by_role=lambda *a, **kw: Many(),
        )
        d = BrowserDriver(None, page, None)
        with self.assertRaises(Paused):
            await d._checkout_controls()

    async def test_zero_checkout_wrong_offer_cannot_submit(self):
        async def evidence(*a, **kw):
            return {"complete": True, "offer_ids": ["other"]}

        d = BrowserDriver(None, None, None, checkout_evidence=evidence)
        d.offer = SimpleNamespace(id="expected")

        async def controls():
            return [(object(), object())]

        d._checkout_controls = controls
        self.assertEqual(await d.checkout_total(timeout=1), "unknown")
        self.assertIsNone(d.checkout_button)

    async def test_free_word_without_price_binding_unknown(self):
        d = BrowserDriver(None, SimpleNamespace(locator=lambda *a: Controls()), None)
        self.assertEqual(await d.inspect_cart(timeout=1), "unknown")


if __name__ == "__main__":
    unittest.main()
