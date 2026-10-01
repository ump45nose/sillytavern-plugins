import unittest
from platforms.v2ex.adapter import classify, execute


class Session:
    closed = False

    def __init__(self):
        self.headers = {}
        self.proxies = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        Session.closed = True


class Provider:
    @staticmethod
    def sign(s):
        return [{"name": "今日签到", "value": "20261001 每日登录奖励"}]


class V2exTests(unittest.TestCase):
    def test_confirmation(self):
        self.assertTrue(classify(Provider.sign(None), "2026-10-01"))
        self.assertFalse(classify(Provider.sign(None), "2026-10-02"))
        self.assertFalse(
            classify(
                [*Provider.sign(None), {"name": "签到失败", "value": "x"}], "2026-10-01"
            )
        )
        self.assertFalse(classify(None, "2026-10-01"))

    def test_fake_session(self):
        c = dict(
            run_id="r", platform="v2ex", account="test", business_date="2026-10-01"
        )
        out = execute(c, Provider, Session, "synthetic-cookie")
        self.assertEqual(out["business"]["reward"], "complete")
        self.assertTrue(Session.closed)

    def test_missing_cookie_no_calls(self):
        c = dict(
            run_id="r", platform="v2ex", account="test", business_date="2026-10-01"
        )
        self.assertEqual(execute(c, None, None, "")["execution_status"], "failed")


class ProviderParityTests(unittest.TestCase):
    def test_original_provider_parity(self):
        import importlib.util
        from pathlib import Path
        from platforms.v2ex.provider import V2ex

        path = Path(__file__).parent / "fixtures/v2ex_sign_original.py"
        spec = importlib.util.spec_from_file_location("original_fixture", path)
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)

        class Response:
            def __init__(self, text):
                self.text = text

        class Fake:
            def __init__(self, mode):
                self.mode = mode
                self.calls = []

            def get(self, url, **kwargs):
                self.calls.append(
                    (url, {k: v for k, v in kwargs.items() if k != "verify"})
                )
                if self.mode == "invalid":
                    return Response("sign in required")
                if url.endswith("/balance"):
                    return Response(
                        '<td class="d"><span class="gray">20261001 每日登录奖励</span></td>'
                    )
                target = (
                    "/balance"
                    if self.mode == "already"
                    else "/mission/daily/redeem?once=test"
                )
                return Response(
                    f'<input type="button" class="super normal button" value="领取" onclick="location.href = \'{target}\';" /><div class="cell">1天</div>'
                )

        for mode in ("invalid", "already", "new"):
            left, right = Fake(mode), Fake(mode)
            self.assertEqual(V2ex.sign(left), original.sign(right))
            self.assertEqual(left.calls, right.calls)
