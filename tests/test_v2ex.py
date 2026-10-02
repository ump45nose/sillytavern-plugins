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
    def sign(s, **kwargs):
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


class V2exRecoveryTests(unittest.TestCase):
    context = dict(
        run_id="r", platform="v2ex", account="test", business_date="2026-10-01"
    )

    def test_ambiguous_redeem_is_read_only_on_restart(self):
        import tempfile
        from platforms.v2ex.provider import V2ex

        calls = []

        class Response:
            def __init__(self, text):
                self.text = text

        class Fake(Session):
            def get(self, url, **kwargs):
                calls.append(url)
                if "/redeem" in url:
                    raise TimeoutError("synthetic timeout")
                if url.endswith("/balance"):
                    return Response(
                        '<td class="d"><span class="gray">20261001 每日登录奖励</span></td>'
                    )
                return Response(
                    '<input type="button" class="super normal button" value="领取" onclick="location.href = \'/mission/daily/redeem?once=fixture\';" /><div class="cell">1天</div>'
                )

        with tempfile.TemporaryDirectory() as directory:
            first = execute(self.context, V2ex, Fake, "synthetic", state_dir=directory)
            self.assertEqual(first["business"]["checkin"], "unknown")
            second = execute(self.context, V2ex, Fake, "synthetic", state_dir=directory)
            self.assertEqual(second["business"]["reward"], "complete")
            self.assertEqual(sum("/redeem" in url for url in calls), 1)
            calls.clear()
            execute(self.context, V2ex, Fake, "synthetic", state_dir=directory)
            self.assertEqual(calls, [])

    def test_final_read_error_does_not_erase_balance_confirmation(self):
        import tempfile
        from platforms.v2ex.provider import V2ex

        class Response:
            def __init__(self, text):
                self.text = text

        class Fake(Session):
            daily_reads = 0

            def get(self, url, **kwargs):
                if url.endswith("/balance"):
                    return Response(
                        '<td class="d"><span class="gray">20261001 每日登录奖励</span></td>'
                    )
                if url.endswith("/mission/daily"):
                    self.daily_reads += 1
                    if self.daily_reads > 1:
                        raise TimeoutError("fixture")
                return Response(
                    '<input type="button" class="super normal button" value="领取" onclick="location.href = \'/balance\';" />'
                )

        with tempfile.TemporaryDirectory() as directory:
            out = execute(self.context, V2ex, Fake, "synthetic", state_dir=directory)
            self.assertEqual(out["execution_status"], "failed")
            self.assertEqual(
                out["business"], {"checkin": "complete", "reward": "complete"}
            )
            self.assertEqual(
                execute(self.context, V2ex, None, "synthetic", state_dir=directory)[
                    "execution_status"
                ],
                "ok",
            )

    def test_legacy_result_import_requires_matching_account_and_date(self):
        import tempfile
        import json
        from pathlib import Path
        from common.model import result

        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "confirmed.json"
            saved.write_text(
                json.dumps(
                    result(
                        self.context,
                        "ok",
                        "reward_confirmed",
                        {"checkin": "complete", "reward": "complete"},
                    )
                )
            )
            out = execute(
                self.context,
                None,
                None,
                "synthetic",
                state_dir=directory,
                confirmed_path=saved,
            )
            self.assertEqual(out["execution_status"], "ok")
            saved.write_text(
                json.dumps(
                    result(
                        {**self.context, "account": "another"},
                        "ok",
                        "reward_confirmed",
                        {"checkin": "complete", "reward": "complete"},
                    )
                )
            )
            self.assertEqual(
                execute(
                    self.context,
                    None,
                    None,
                    "synthetic",
                    state_dir=directory,
                    confirmed_path=saved,
                )["reason"],
                "invalid_action_state",
            )

    def test_corrupt_journal_does_not_open_session(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "http-actions.json").write_text("broken")
            self.assertEqual(
                execute(self.context, None, None, "synthetic", state_dir=directory)[
                    "reason"
                ],
                "invalid_action_state",
            )


class V2exStreamingTests(unittest.TestCase):
    def make_response(self, count, length=None, status=200):
        class Response:
            status_code = status
            headers = {} if length is None else {"Content-Length": str(length)}
            closed = False
            reads = 0

            def iter_content(self, chunk_size):
                for _ in range(count):
                    self.reads += 1
                    yield b"x" * chunk_size

            def close(self):
                self.closed = True

        return Response()

    def request(self, response):
        from platforms.v2ex.adapter import bounded_session

        self.arguments = None
        owner = self

        class Base:
            def request(self, method, url, **kwargs):
                owner.arguments = kwargs
                return response

        return bounded_session(Base)().request(
            "GET", "https://fixture.invalid", verify=False, stream=False
        )

    def test_stream_without_content_length_stops_at_byte_cap(self):
        response = self.make_response(100000)
        with self.assertRaisesRegex(ValueError, "response_limit"):
            self.request(response)
        self.assertEqual(response.reads, 17)
        self.assertTrue(response.closed)
        self.assertTrue(self.arguments["verify"])
        self.assertTrue(self.arguments["stream"])
        self.assertFalse(self.arguments["allow_redirects"])
        self.assertEqual(self.arguments["timeout"], 30)

    def test_content_length_and_redirect_reject_before_buffering(self):
        for response in [
            self.make_response(1000, length=1048577),
            self.make_response(1000, status=302),
        ]:
            with self.assertRaises(ValueError):
                self.request(response)
            self.assertEqual(response.reads, 0)
            self.assertTrue(response.closed)

    def test_exact_byte_cap_is_usable_after_closing_stream(self):
        response = self.request(self.make_response(16))
        self.assertEqual(len(response._content), 1048576)
        self.assertTrue(response._content_consumed)
        self.assertTrue(response.closed)


class V2exRequestsBindingTests(unittest.TestCase):
    def test_requests_redirect_does_not_eagerly_consume_body(self):
        # Exercise requests.Session.send's Response.next branch, which otherwise
        # buffers redirects even with stream=True and allow_redirects=False.
        try:
            import requests
        except ImportError:
            try:
                from pip._vendor import requests
            except ImportError:
                self.skipTest(
                    "requests binding unavailable; fake streaming tests still run"
                )
        from platforms.v2ex.adapter import bounded_session

        class Raw:
            reads = 0
            closed = False

            def read(self, *args, **kwargs):
                self.reads += 1
                raise AssertionError("redirect body must not be buffered")

            def close(self):
                self.closed = True

            def release_conn(self):
                pass

        raw = Raw()

        class Adapter(requests.adapters.BaseAdapter):
            def send(self, request, **kwargs):
                response = requests.Response()
                response.status_code = 302
                response.headers["Location"] = "https://fixture.invalid/redirect"
                response.request = request
                response.raw = raw
                return response

            def close(self):
                pass

        with bounded_session(requests.Session)() as session:
            session.trust_env = False
            session.mount("https://", Adapter())
            with self.assertRaisesRegex(ValueError, "unexpected_redirect"):
                session.get("https://fixture.invalid/fixture", verify=False)
        self.assertEqual(raw.reads, 0)
        self.assertTrue(raw.closed)
