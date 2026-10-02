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


# Metadata fixture from the hash-pinned external provider, not its implementation.
PINNED_CODES = [
    "",
    "ecs",
    "computenest",
    "yitian",
    "wuying",
    "cloudnative",
    "storage",
    "database",
    "polardb",
    "modelscope",
    "vision",
    "dns",
    "iot",
    "aliyun_linux",
    "tongyi",
]


class AliyunRecoveryTests(unittest.TestCase):
    def test_all_15_communities_including_default_are_required(self):
        from common.model import validate

        client = FakeClient()
        original = client.request
        seen = []

        def request(method, url, **kwargs):
            if url.endswith("getUserSpaceSignInDetail"):
                seen.append(kwargs["params"]["excode"])
                if kwargs["params"]["excode"] == "ecs":
                    raise TimeoutError("fixture")
            return original(method, url, **kwargs)

        client.request = request
        out = sign_only(
            CTX, client, [{"code": c} for c in PINNED_CODES], API, lambda _: None
        )
        self.assertEqual(seen, PINNED_CODES)
        self.assertEqual(out["business"]["checkin"], "unknown")
        self.assertEqual(out["business"]["community_0_checkin"], "complete")
        self.assertEqual(out["business"]["community_1_checkin"], "unknown")
        self.assertEqual(len(out["business"]), 32)
        validate(out, CTX)

    def test_later_detail_error_preserves_prior_facts_without_aggregate_completion(
        self,
    ):
        import json

        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            original = client.request

            def request(method, url, **kwargs):
                if (
                    url.endswith("getUserSpaceSignInDetail")
                    and kwargs["params"]["excode"] == "two"
                ):
                    raise TimeoutError("fixture")
                return original(method, url, **kwargs)

            client.request = request
            groups = [{"code": "one"}, {"code": "two"}]
            out = sign_only(CTX, client, groups, API, lambda _: None, directory)
            self.assertEqual(out["business"]["checkin"], "unknown")
            state = json.loads((Path(directory) / "http-actions.json").read_text())
            self.assertEqual(state["groups"]["one"]["sign"], "complete")
            self.assertEqual(state["groups"]["two"]["sign"], "unknown")
            restored = FakeClient()
            out = sign_only(CTX, restored, groups, API, lambda _: None, directory)
            self.assertEqual(out["business"]["checkin"], "complete")
            self.assertFalse(any(u.endswith("actionLog") for _, u in restored.calls))
            self.assertEqual(
                sum(u.endswith("receiveSignInBonus") for _, u in restored.calls), 1
            )

    def test_write_timeout_is_read_back_and_not_replayed_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(signed=False)
            original = client.request

            def request(method, url, **kwargs):
                if url.endswith("actionLog"):
                    client.calls.append((method, url))
                    client.signed = True
                    raise TimeoutError("fixture")
                return original(method, url, **kwargs)

            client.request = request
            out = sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            self.assertEqual(out["business"]["checkin"], "complete")
            # A stale read on restart must not override the persisted positive receipt.
            client.signed = False
            sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            self.assertEqual(sum(u.endswith("actionLog") for _, u in client.calls), 1)

    def test_unresolved_sign_intent_only_reads_on_subsequent_run(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(signed=False)
            original = client.request

            def request(method, url, **kwargs):
                if url.endswith("actionLog"):
                    client.calls.append((method, url))
                    raise TimeoutError("fixture")
                return original(method, url, **kwargs)

            client.request = request
            for _ in range(2):
                out = sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
                self.assertEqual(out["business"]["checkin"], "unknown")
            self.assertEqual(sum(u.endswith("actionLog") for _, u in client.calls), 1)

    def test_unresolved_bonus_does_not_repeat_or_infer_receipt_from_false_eligibility(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient()
            original = client.request
            eligible = True

            def request(method, url, **kwargs):
                if url.endswith("receiveSignInBonus"):
                    client.calls.append((method, url))
                    raise TimeoutError("fixture")
                if url.endswith("assessSignInBonusQualification"):
                    return {"code": 200, "data": eligible}
                return original(method, url, **kwargs)

            client.request = request
            sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            eligible = False
            out = sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            self.assertEqual(
                sum(u.endswith("receiveSignInBonus") for _, u in client.calls), 1
            )
            self.assertEqual(out["business"]["reward"], "unknown")
            self.assertEqual(out["business"]["checkin"], "complete")

    def test_pending_score_timeout_is_read_back_before_future_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(pending=2)
            original = client.request

            def request(method, url, **kwargs):
                if url.endswith("receiveAllPendingScore"):
                    client.calls.append((method, url))
                    raise TimeoutError("fixture")
                return original(method, url, **kwargs)

            client.request = request
            sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            self.assertEqual(
                sum(u.endswith("receiveAllPendingScore") for _, u in client.calls), 1
            )
            client.pending = 0
            out = sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            self.assertEqual(out["business"]["reward"], "complete")

    def test_corrupt_journal_prevents_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "http-actions.json").write_text("broken")
            client = FakeClient()
            out = sign_only(CTX, client, GROUPS, API, lambda _: None, directory)
            self.assertEqual(out["reason"], "invalid_action_state")
            self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
