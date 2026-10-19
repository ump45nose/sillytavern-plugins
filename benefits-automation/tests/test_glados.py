"""GLaDOS protocol/workflow regressions; no real site requests or credentials."""

from datetime import datetime
from http.client import IncompleteRead
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from common.model import validate
from platforms.glados import adapter
from platforms.glados.adapter import execute
from platforms.glados.provider import (
    ALREADY_MESSAGES, MAX_BODY, REQUEST_TIMEOUT, Client, NoRedirect, ProviderError,
    accepted, read_points, validate_settings,
)

CONTEXT = {"run_id": "fixture", "platform": "glados", "account": "main",
           "business_date": "2026-10-19"}
COOKIE = "gld:sess=fixture-session; gld:sess.sig=fixture-signature; other=1"
UA = "Mozilla/5.0 fixture-agent"
ORIGIN = "https://glados.cloud"
ROOT = Path(__file__).resolve().parents[1]


def record(day="2026-10-19", change="2", business="checkin:2026-10-19", hour=8):
    timestamp = datetime.fromisoformat(f"{day}T{hour:02}:00:00+08:00").timestamp() * 1000
    return {"business": business, "time": timestamp, "change": change, "balance": "12"}


def points(signed=False, balance="10", **extra):
    return {"code": 0, "points": balance, "history": [record()] if signed else [],
            "streak": 4, **extra}


class FakeClient:
    def __init__(self, initial=None, final=None, reply=None):
        self.snapshots = [initial if initial is not None else points(),
                          final if final is not None else points(True, "12")]
        self.reply = reply if reply is not None else {"code": 0, "points": 2}
        self.calls = []
        self.status_error = None
        self.status_reads = 0

    def status(self):
        self.calls.append("status")
        self.status_reads += 1
        if self.status_error:
            raise self.status_error
        return 10 if self.status_reads == 1 else 11

    def points(self):
        self.calls.append("points")
        value = self.snapshots.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def checkin(self):
        self.calls.append("checkin")
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def run_client(self, client, context=CONTEXT, **kwargs):
        out = execute(context, client, self.directory.name, **kwargs)
        validate(out, context)
        return out

    def test_new_checkin_is_read_submitted_once_and_read_back(self):
        client = FakeClient()
        out = self.run_client(client)
        self.assertEqual(client.calls, ["status", "points", "checkin", "points", "status"])
        self.assertEqual(out["business"], {"checkin": "complete", "reward": "complete", "balance": "complete"})
        metrics = out["details"]["metrics"]
        self.assertEqual(metrics["balance"]["delta"], 2)
        self.assertEqual(metrics["reward"]["current"], 2)
        self.assertEqual(metrics["remaining_days"]["after"], 11)

    def test_today_record_not_first_skips_write_and_zero_reward_is_known(self):
        current = points(history=[record(business="system:invitation"), record(change=0)])
        client = FakeClient(initial=current)
        out = self.run_client(client)
        self.assertNotIn("checkin", client.calls)
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertEqual(out["details"]["metrics"]["reward"]["current"], 0)
        self.assertEqual(out["details"]["metrics"]["balance"]["delta"], 0)

    def test_status_mode_never_signs_or_fabricates_success(self):
        client = FakeClient()
        out = self.run_client(client, status_only=True)
        self.assertNotIn("checkin", client.calls)
        self.assertEqual(out["business"]["checkin"], "incomplete")
        self.assertEqual(out["business"]["reward"], "unknown")

    def test_previous_day_record_does_not_complete_today(self):
        client = FakeClient(initial=points(history=[record("2026-10-18")]))
        self.assertEqual(self.run_client(client)["business"]["checkin"], "complete")
        self.assertEqual(client.calls.count("checkin"), 1)

    def test_malformed_or_missing_history_never_authorizes_a_write(self):
        for value in ({"code": 0, "points": 10}, points(history=[{}]),
                      points(history=[record(change=-1)]), points(history="not an array")):
            with self.subTest(value=value):
                client = FakeClient(initial=value)
                out = self.run_client(client)
                self.assertNotIn("checkin", client.calls)
                self.assertEqual(out["business"]["checkin"], "unknown")

    def test_authentication_failure_before_actions_is_visible(self):
        client = FakeClient()
        client.status_error = ProviderError("authentication_invalid")
        out = self.run_client(client)
        self.assertEqual(client.calls, ["status"])
        self.assertEqual(out["reason"], "authentication_invalid")
        self.assertEqual(out["execution_status"], "failed")

    def test_optional_status_failure_does_not_prevent_points_confirmed_checkin(self):
        client = FakeClient()
        client.status_error = ProviderError("business_response_unrecognized")
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertIsNone(out["details"]["metrics"]["remaining_days"]["current"])

    def test_unavailable_preflight_points_prevents_write(self):
        client = FakeClient(initial=ProviderError("transport_error"))
        out = self.run_client(client)
        self.assertNotIn("checkin", client.calls)
        self.assertEqual(out["reason"], "transport_error")

    def test_post_timeout_recovers_with_history_without_second_write(self):
        client = FakeClient(reply=ProviderError("transport_error"))
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertEqual(client.calls.count("checkin"), 1)
        again = FakeClient(initial=points(True, "12"))
        self.assertEqual(self.run_client(again)["business"]["checkin"], "complete")
        self.assertNotIn("checkin", again.calls)

    def test_unconfirmed_post_is_not_repeated_in_later_invocation(self):
        client = FakeClient(final=points(False, "15"), reply=ProviderError("transport_error"))
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "unknown")
        self.assertEqual(out["details"]["metrics"]["balance"]["delta"], 5)
        self.assertIsNone(out["details"]["metrics"]["reward"]["current"])
        again = FakeClient()
        out = self.run_client(again)
        self.assertNotIn("checkin", again.calls)
        self.assertEqual(out["reason"], "checkin_pending_confirmation")

    def test_known_ack_survives_missing_readback_and_next_invocation(self):
        client = FakeClient(final=ProviderError("transport_error"))
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "complete")
        balance = out["details"]["metrics"]["balance"]
        self.assertEqual(balance["current"], 10)
        self.assertIsNone(balance["after"])
        self.assertIsNone(balance["delta"])
        self.assertEqual(out["business"]["balance"], "unknown")
        again = FakeClient(initial=points())
        out = self.run_client(again)
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertNotIn("checkin", again.calls)

    def test_auth_expiry_during_readback_is_visible_without_revoking_checkin(self):
        client = FakeClient(final=ProviderError("authentication_invalid"))
        out = self.run_client(client)
        self.assertEqual(out["reason"], "authentication_invalid")
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertEqual(out["business"]["balance"], "unknown")
        self.assertEqual(client.calls.count("checkin"), 1)

    def test_missing_reward_is_unknown_not_zero(self):
        entry = record()
        del entry["change"]
        client = FakeClient(reply={"code": 0}, final=points(history=[entry]))
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertEqual(out["business"]["reward"], "unknown")
        self.assertIsNone(out["details"]["metrics"]["reward"]["current"])

    def test_recognized_duplicate_ack_does_not_invent_a_reward(self):
        client = FakeClient(final=points(), reply={"code": 1, "message": "Please Try Tomorrow"})
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "complete")
        self.assertEqual(out["business"]["reward"], "unknown")

    def test_unknown_code_one_is_not_success_and_keeps_intent(self):
        client = FakeClient(final=points(), reply={"code": 1, "message": "unknown rejection"})
        out = self.run_client(client)
        self.assertEqual(out["business"]["checkin"], "unknown")
        self.assertNotEqual(out["reason"], "checkin_confirmed")
        again = FakeClient()
        self.run_client(again)
        self.assertNotIn("checkin", again.calls)

    def test_explicit_device_rejection_can_be_retried_after_configuration_fix(self):
        client = FakeClient(final=points(), reply={"code": 4, "reason": "device-mismatch",
                                                   "message": "fixture private detail"})
        out = self.run_client(client)
        self.assertEqual(out["reason"], "device_mismatch")
        self.assertEqual(out["business"]["checkin"], "blocked")
        self.assertNotIn("fixture private detail", json.dumps(out))
        fixed = FakeClient()
        self.assertEqual(self.run_client(fixed)["business"]["checkin"], "complete")
        self.assertEqual(fixed.calls.count("checkin"), 1)

    def test_automated_checkin_rejection_is_visible(self):
        client = FakeClient(final=points(), reply={"code": 4, "message": "Automated check-in detected"})
        out = self.run_client(client)
        self.assertEqual(out["reason"], "automated_checkin_rejected")
        self.assertEqual(out["business"]["checkin"], "blocked")

    def test_bad_persisted_state_blocks_network(self):
        (Path(self.directory.name) / "checkin.json").write_text('{"status":"complete"}')
        client = FakeClient()
        self.assertEqual(self.run_client(client)["reason"], "invalid_action_state")
        self.assertEqual(client.calls, [])

    def test_pending_daily_checkin_does_not_suppress_next_days_action(self):
        self.run_client(FakeClient(final=points(), reply=ProviderError("transport_error")))
        tomorrow = {**CONTEXT, "business_date": "2026-10-20"}
        client = FakeClient(final=points(history=[record("2026-10-20")]))
        self.run_client(client, tomorrow)
        self.assertEqual(client.calls.count("checkin"), 1)


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, length=None):
        super().__init__(body)
        self.status = status
        self.headers = {} if length is None else {"Content-Length": str(length)}
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ProtocolTests(unittest.TestCase):
    def client(self, response, **kwargs):
        opener = Opener(response)
        return Client(ORIGIN, COOKIE, UA, opener=opener, **kwargs), opener

    def test_exact_origin_cookie_ua_and_hostname_token(self):
        response = Response(b'{"code":0}')
        client, opener = self.client(response)
        client.checkin()
        request, timeout = opener.calls[0]
        self.assertEqual(request.full_url, ORIGIN + "/api/user/checkin")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"token": "glados.cloud"})
        self.assertEqual(request.get_header("Cookie"), COOKIE)
        self.assertEqual(request.get_header("User-agent"), UA)
        self.assertEqual(timeout, REQUEST_TIMEOUT)
        self.assertTrue(response.closed)

    def test_explicit_token_override_is_preserved(self):
        client, opener = self.client(Response(b'{"code":0}'), token="glados_network")
        client.checkin()
        self.assertEqual(json.loads(opener.calls[0][0].data)["token"], "glados_network")

    def test_no_transport_retry_or_domain_failover(self):
        client, opener = self.client(URLError("fixture-secret-error"))
        with self.assertRaisesRegex(ProviderError, "^transport_error$"):
            client.checkin()
        self.assertEqual(len(opener.calls), 1)

    def test_partial_http_read_is_reported_without_retry(self):
        class BrokenResponse(Response):
            def read(self, size=-1):
                raise IncompleteRead(b"private response")

        response = BrokenResponse(b"")
        client, opener = self.client(response)
        with self.assertRaisesRegex(ProviderError, "^transport_error$"):
            client.checkin()
        self.assertEqual(len(opener.calls), 1)
        self.assertTrue(response.closed)

    def test_stream_is_bounded_without_trusting_length(self):
        response = Response(b"x" * (MAX_BODY + 2))
        client, _ = self.client(response)
        with self.assertRaisesRegex(ProviderError, "^response_too_large$"):
            client.points()
        self.assertEqual(response.read_sizes, [MAX_BODY + 1])
        self.assertTrue(response.closed)

    def test_oversized_declared_response_is_not_read(self):
        response = Response(b'{}', length=MAX_BODY + 1)
        client, _ = self.client(response)
        with self.assertRaisesRegex(ProviderError, "^response_too_large$"):
            client.points()
        self.assertEqual(response.read_sizes, [])
        self.assertTrue(response.closed)

    def test_redirect_handler_never_replays_credentials(self):
        handler = NoRedirect()
        request = Request(ORIGIN + "/api/user/points", headers={"Cookie": COOKIE})
        with self.assertRaisesRegex(ProviderError, "^unexpected_redirect$"):
            handler.http_error_302(request, io.BytesIO(), 302, "Found",
                                   {"location": "https://other.invalid/collect"})

    def test_html_boolean_code_and_invalid_json_are_not_business_success(self):
        for raw in (b'<html>login</html>', b'{"code":true}', b'[]', b'{"code":"0"}'):
            with self.subTest(raw=raw):
                client, _ = self.client(Response(raw))
                with self.assertRaisesRegex(ProviderError, "^invalid_response$"):
                    client.points()

    def test_http_401_is_auth_failure_and_non_200_zero_is_not_accepted(self):
        error = HTTPError(ORIGIN, 401, "private", {}, io.BytesIO(b'{"code":-2}'))
        client, _ = self.client(error)
        with self.assertRaisesRegex(ProviderError, "^authentication_invalid$"):
            client.points()
        client, _ = self.client(Response(b'{"code":0}', status=500))
        with self.assertRaisesRegex(ProviderError, "^http_error$"):
            client.checkin()

    def test_forbidden_response_without_business_code_is_not_auth_expiry(self):
        for raw in (b'{"message":"forbidden"}', b'<html>blocked</html>'):
            with self.subTest(raw=raw):
                client, _ = self.client(Response(raw, status=403))
                with self.assertRaisesRegex(ProviderError, "^access_denied$"):
                    client.points()

    def test_known_messages_only_accept_the_expected_code(self):
        for message in ALREADY_MESSAGES:
            self.assertTrue(accepted({"code": 1, "message": message}))
            self.assertFalse(accepted({"code": -2, "message": message}))
            self.assertFalse(accepted({"code": True, "message": message}))

    def test_configuration_rejects_incomplete_cookie_and_missing_ua(self):
        for cookie in ("", "gld:sess=x", "koa:sess.sig=x", COOKIE + "; gld:sess=second", COOKIE + "\n"):
            with self.subTest(cookie=cookie):
                with self.assertRaises(ProviderError):
                    validate_settings(ORIGIN, cookie, UA)
        with self.assertRaisesRegex(ProviderError, "^missing_or_invalid_user_agent$"):
            validate_settings(ORIGIN, COOKIE, "")
        self.assertEqual(validate_settings(ORIGIN, "koa:sess=x; koa:sess.sig=y", UA),
                         (ORIGIN, "glados.cloud"))

    def test_configuration_rejects_origin_fallback_lists_and_redirect_locations(self):
        for origin in ("", "http://glados.cloud", ORIGIN + "/console", ORIGIN + "?x=1",
                       "https://user:pass@glados.cloud", "https://glados.cloud:8443",
                       "https://glados.cloud,https://glados.space", "\n" + ORIGIN):
            with self.subTest(origin=origin):
                with self.assertRaisesRegex(ProviderError, "^missing_or_invalid_origin$"):
                    validate_settings(origin, COOKIE, UA)

    def test_calendar_uses_requested_timezone_and_checkin_business_only(self):
        body = points(history=[record(hour=0)])
        self.assertTrue(read_points(body, "2026-10-19", "Asia/Shanghai").signed)
        self.assertFalse(read_points(body, "2026-10-19", "UTC").signed)
        self.assertFalse(read_points(points(history=[record(business="system:invitation")]),
                                     "2026-10-19", "Asia/Shanghai").signed)


class EntrypointTests(unittest.TestCase):
    def invoke(self, runtime, *args, extra_env=None):
        env = {"PATH": os.environ["PATH"], **(extra_env or {})}
        return subprocess.run([sys.executable, str(ROOT / "platforms/glados/run.py"),
                               "--runtime-root", runtime, "--account", "main", *args],
                              env=env, capture_output=True, text=True, timeout=10)

    def test_offline_entry_ignores_even_invalid_network_configuration(self):
        with tempfile.TemporaryDirectory() as runtime:
            child = self.invoke(runtime, extra_env={"GLADOS_ORIGIN": "invalid"})
            self.assertEqual(child.returncode, 1)
            self.assertEqual(json.loads(child.stdout)["reason"], "execution_not_requested")
            self.assertFalse((Path(runtime) / "results").exists())

    def test_missing_credentials_produce_saved_structured_failure(self):
        with tempfile.TemporaryDirectory() as runtime:
            child = self.invoke(runtime, "--execute")
            self.assertEqual(child.returncode, 1)
            out = json.loads(child.stdout)
            self.assertEqual(out["reason"], "missing_or_invalid_origin")
            self.assertEqual(json.loads((Path(runtime) / "results/glados/main/latest.json").read_text())["run_id"],
                             out["run_id"])

    def test_invalid_user_agent_does_not_leak_cookie_into_logs_or_result(self):
        with tempfile.TemporaryDirectory() as runtime:
            child = self.invoke(runtime, "--execute", extra_env={"GLADOS_ORIGIN": ORIGIN, "GLADOS_COOKIE": COOKIE})
            self.assertEqual(json.loads(child.stdout)["reason"], "missing_or_invalid_user_agent")
            for path in Path(runtime).rglob("*"):
                if path.is_file():
                    self.assertNotIn("fixture-session", path.read_text())


class CookieCloudBindingTests(unittest.TestCase):
    def environment(self, directory):
        return {
            **{"BENEFITS_" + key.upper(): value for key, value in CONTEXT.items()},
            "BENEFITS_STATE_DIR": str(Path(directory) / "state"),
            "BENEFITS_RESULT_PATH": str(Path(directory) / "result.json"),
            "GLADOS_ORIGIN": ORIGIN, "GLADOS_USER_AGENT": UA,
            "GLADOS_COOKIE": "gld:sess=old; gld:sess.sig=old",
            "COOKIECLOUD_CONFIG": "/private/cookiecloud.json",
        }

    def test_only_selected_site_cookie_is_used_instead_of_environment_cookie(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(initial=points(True))
            with patch.dict(os.environ, self.environment(directory), clear=True), \
                    patch.object(sys, "argv", ["adapter.py", "--status"]), \
                    patch("common.cookiecloud.cookie_header", return_value=COOKIE) as reader, \
                    patch.object(adapter, "Client", return_value=client) as factory:
                self.assertEqual(adapter.main(), 0)
            reader.assert_called_once_with("/private/cookiecloud.json", "glados.cloud")
            self.assertEqual(factory.call_args.args[1], COOKIE)
            self.assertNotIn("checkin", client.calls)

    def test_cookiecloud_failure_is_visible_and_never_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, self.environment(directory), clear=True), \
                    patch.object(sys, "argv", ["adapter.py"]), \
                    patch("common.cookiecloud.cookie_header", side_effect=ValueError("private payload")), \
                    patch.object(adapter, "Client") as factory:
                self.assertEqual(adapter.main(), 1)
            factory.assert_not_called()
            raw = (Path(directory) / "result.json").read_text()
            self.assertEqual(json.loads(raw)["reason"], "cookiecloud_unavailable")
            self.assertNotIn("private payload", raw)
            self.assertNotIn("gld:sess", raw)

    def test_missing_user_agent_stops_before_contacting_cookiecloud(self):
        with tempfile.TemporaryDirectory() as directory:
            env = self.environment(directory)
            del env["GLADOS_USER_AGENT"]
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(sys, "argv", ["adapter.py"]), \
                    patch("common.cookiecloud.cookie_header") as reader:
                self.assertEqual(adapter.main(), 1)
            reader.assert_not_called()
            out = json.loads((Path(directory) / "result.json").read_text())
            self.assertEqual(out["reason"], "missing_or_invalid_user_agent")


if __name__ == "__main__":
    unittest.main()
