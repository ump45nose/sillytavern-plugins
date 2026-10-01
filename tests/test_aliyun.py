import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from platforms.aliyun.adapter import sign_only, execute, load_provider

CTX = dict(
    run_id="test", platform="aliyun", account="default", business_date="2026-10-01"
)
GROUPS = [{"code": "one"}]
API = "https://fixture.invalid"


class FakeClient:
    def __init__(self, signed=True, auth=True, pending=0):
        self.signed = signed
        self.auth = auth
        self.pending = pending
        self.calls = []
        self.session = SimpleNamespace(trust_env=True, proxies={}, close=lambda: None)

    def ensure_session(self):
        return {"ok": self.auth}

    def get_user_score(self):
        return 10

    def get_pending_score(self):
        return self.pending

    def get_tasks(self, group):
        return {"actionCode": "sign"}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if url.endswith("getUserSpaceSignInDetail"):
            return {
                "data": {
                    "taskGroupId": "group",
                    "signInList": [
                        {"today": True, "status": "2" if self.signed else "1"}
                    ],
                }
            }
        if url.endswith("actionLog"):
            self.signed = True
            return {"code": 200}
        if url.endswith("assessSignInBonusQualification"):
            return {"code": 200, "data": True}
        return {"code": 200}


class AliyunTests(unittest.TestCase):
    def test_already_signed(self):
        client = FakeClient()
        out = sign_only(CTX, client, GROUPS, API, lambda _: None)
        self.assertEqual(out["execution_status"], "ok")
        self.assertFalse(any(u.endswith("actionLog") for _, u in client.calls))

    def test_submit_once_then_read(self):
        client = FakeClient(signed=False)
        out = sign_only(CTX, client, GROUPS, API, lambda _: None)
        self.assertEqual(out["execution_status"], "ok")
        self.assertEqual(sum(u.endswith("actionLog") for _, u in client.calls), 1)

    def test_auth_failure_no_actions(self):
        client = FakeClient(auth=False)
        self.assertEqual(
            sign_only(CTX, client, GROUPS, API)["reason"], "authentication_invalid"
        )
        self.assertEqual(client.calls, [])

    def test_unknown_pending_not_success(self):
        out = sign_only(CTX, FakeClient(pending=None), GROUPS, API, lambda _: None)
        self.assertEqual(out["execution_status"], "failed")
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertEqual(out["business"]["reward"], "unknown")

    def test_timeout_write_never_replayed(self):
        client = FakeClient(signed=False)
        original = client.request

        def request(method, url, **kwargs):
            if url.endswith("actionLog"):
                client.calls.append((method, url))
                raise TimeoutError("dummy secret not output")
            return original(method, url, **kwargs)

        client.request = request
        out = sign_only(CTX, client, GROUPS, API, lambda _: None)
        self.assertEqual(out["reason"], "provider_error")
        self.assertEqual(sum(u.endswith("actionLog") for _, u in client.calls), 1)
        self.assertNotIn("dummy secret", str(out))

    def test_no_verified_community_not_success(self):
        out = sign_only(CTX, FakeClient(), [], API, lambda _: None)
        self.assertEqual(out["execution_status"], "failed")

    def test_missing_claim_code_unknown(self):
        client = FakeClient(pending=2)
        original = client.request

        def request(method, url, **kwargs):
            return (
                {}
                if url.endswith("receiveAllPendingScore")
                else original(method, url, **kwargs)
            )

        client.request = request
        self.assertEqual(
            sign_only(CTX, client, GROUPS, API, lambda _: None)["execution_status"],
            "failed",
        )

    def test_unpinned_source_not_executed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "daily.py"
            path.write_text("raise AssertionError('must not execute')")
            with self.assertRaises(ValueError):
                load_provider(path)

    def test_invalid_cookie_before_client(self):
        self.assertEqual(
            execute(CTX, None, "bad\ncookie")["reason"], "missing_or_invalid_cookie"
        )

    def test_scope_config_and_session_cleanup(self):
        closed = []
        client = FakeClient()
        client.session.close = lambda: closed.append(True)

        def factory(account, cfg, cache):
            self.assertEqual(cfg.max_retries, 1)
            self.assertFalse(cfg.enable_scene)
            self.assertFalse(cfg.enable_video)
            self.assertEqual(cache, {})
            self.assertFalse(hasattr(account, "password"))
            return client

        provider = SimpleNamespace(
            Account=lambda **kw: SimpleNamespace(**kw),
            AppConfig=lambda **kw: SimpleNamespace(**kw),
            AliyunDevClient=factory,
            TASK_GROUPS=GROUPS,
            API=API,
        )
        out = execute(CTX, provider, "dummy_cookie")
        self.assertEqual(out["execution_status"], "ok")
        self.assertEqual(closed, [True])
        self.assertFalse(client.session.trust_env)


if __name__ == "__main__":
    unittest.main()
