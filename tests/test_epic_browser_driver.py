import unittest
from types import SimpleNamespace
from platforms.epic.browser_driver import BrowserDriver, clean_target
from platforms.epic.workflow import Paused


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


class Controls:
    async def count(self):
        return 1

    def nth(self, index):
        return self

    async def is_visible(self):
        return True


class DriverTests(unittest.IsolatedAsyncioTestCase):
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
