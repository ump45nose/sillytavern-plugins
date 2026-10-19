import io
import json
import os
from http.client import IncompleteRead
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

from common.model import validate
from platforms.yanxuan.adapter import execute
from platforms.yanxuan.client import (
    Client, LOGIN_PATH, MAX_RESPONSE, NoRedirect, POINTS_PATH, QueryError,
    parse_points,
)

CONTEXT = {
    "run_id": "fixture-run", "platform": "yanxuan", "account": "fixture",
    "business_date": "2026-10-19",
}
COOKIE = "yx_csrf=synthetic%2Fcsrf; yx_userid=synthetic-user; other=synthetic-session"


class Response(io.BytesIO):
    def __init__(self, value, headers=None, raw=None, status=200):
        super().__init__(raw if raw is not None else json.dumps(value).encode())
        self.status = status
        self.headers = headers or {}


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def points(balance=40, pending=2, **extra):
    return {
        "code": "200",
        "data": {
            "userPointSimpleInfo": {"totalPoint": balance, "unReceivedPoint": pending},
            "availablePoint": 35, **extra,
        },
    }


def ready_opener(response=None):
    return Opener(
        Response({"code": "200", "data": True}),
        Response(points() if response is None else response),
    )


class YanxuanQueryTests(unittest.TestCase):
    def test_snapshot_uses_only_official_read_operations(self):
        opener = ready_opener()
        output = execute(CONTEXT, COOKIE, opener=opener)
        validate(output, CONTEXT)
        self.assertEqual(output["execution_status"], "ok")
        self.assertEqual(output["business"], {"points_query": "complete"})
        self.assertNotIn("checkin", output["business"])
        self.assertEqual(output["details"]["metrics"]["balance"]["current"], 40)
        self.assertEqual(output["details"]["metrics"]["pending_points"]["current"], 2)
        self.assertEqual(output["details"]["metrics"]["available_points"]["current"], 35)
        self.assertEqual(len(opener.calls), 2)
        for (request, timeout), path, method in zip(
            opener.calls, [LOGIN_PATH, POINTS_PATH], ["GET", "POST"]
        ):
            target = urlsplit(request.full_url)
            self.assertEqual(target.hostname, "m.you.163.com")
            self.assertEqual(target.path, path)
            self.assertEqual(request.get_method(), method)
            self.assertEqual(parse_qs(target.query), {"csrf_token": ["synthetic/csrf"]})
            self.assertEqual(request.get_header("Cookie"), COOKIE)
            self.assertEqual(timeout, 15)
        self.assertEqual(opener.calls[1][0].data, b"")
        for metric in output["details"]["metrics"].values():
            self.assertIsNone(metric["delta"])
            self.assertIsNone(metric["before"])
            self.assertIsNone(metric["after"])
        self.assertNotIn(COOKIE, json.dumps(output))
        self.assertNotIn("synthetic-session", json.dumps(output))

    def test_login_false_stops_before_points_query(self):
        opener = Opener(Response({"code": "200", "data": False}))
        output = execute(CONTEXT, COOKIE, opener=opener)
        self.assertEqual(output["reason"], "authentication_invalid")
        self.assertEqual(output["execution_status"], "failed")
        self.assertEqual(len(opener.calls), 1)

    def test_unknown_login_payload_does_not_guess_truthiness(self):
        for value in [None, {}, {"loggedIn": True}, "true", 1]:
            with self.subTest(value=value):
                opener = Opener(Response({"code": 200, "data": value}))
                output = execute(CONTEXT, COOKIE, opener=opener)
                self.assertEqual(output["reason"], "authentication_unconfirmed")
                self.assertEqual(len(opener.calls), 1)

    def test_http_200_with_business_rejection_is_not_success(self):
        for code in [401, "401", 403, "403"]:
            with self.subTest(code=code):
                output = execute(CONTEXT, COOKIE, opener=ready_opener({"code": code}))
                self.assertEqual(output["reason"], "authentication_rejected")
                self.assertEqual(output["business"], {"points_query": "unknown"})

    def test_unknown_schema_and_code_do_not_default_balance_to_zero(self):
        for response, reason in [
            ({"code": 200, "data": {}}, "points_balance_unconfirmed"),
            ({"code": 200, "data": None}, "response_schema_unconfirmed"),
            ({"code": 200, "data": {"userPointSimpleInfo": {}}}, "points_balance_unconfirmed"),
            ({"code": 500, "errorCode": "sensitive-body"}, "points_query_rejected"),
            ([], "response_schema_unconfirmed"),
        ]:
            with self.subTest(response=response):
                output = execute(CONTEXT, COOKIE, opener=ready_opener(response))
                self.assertEqual(output["reason"], reason)
                self.assertEqual(output["details"]["metrics"], {})
                self.assertNotIn("sensitive-body", json.dumps(output))

    def test_zero_is_valid_and_missing_secondary_metrics_remain_unknown(self):
        observed = parse_points({
            "code": 200, "data": {"userPointSimpleInfo": {"totalPoint": 0}}
        })
        self.assertEqual(observed["balance"], 0)
        self.assertIsNone(observed["pending_points"])
        self.assertIsNone(observed["available_points"])

    def test_invalid_balances_are_not_reported(self):
        for value in [None, True, False, -1, "unknown", "NaN", "Infinity", 1e13, 10 ** 400]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(QueryError, "points_balance_unconfirmed"):
                    parse_points(points(value))

    def test_bad_credentials_and_headers_make_no_requests(self):
        for cookie, agent, reason in [
            ("", "Mozilla/5.0", "missing_or_invalid_cookie"),
            ("yx_userid=synthetic", "Mozilla/5.0", "csrf_cookie_missing"),
            ("yx_csrf=", "Mozilla/5.0", "csrf_cookie_missing"),
            ("yx_csrf=synthetic%0Ainjected", "Mozilla/5.0", "csrf_cookie_invalid"),
            (COOKIE + "\r\nInjected: bad", "Mozilla/5.0", "missing_or_invalid_cookie"),
            (COOKIE, "测试agent", "invalid_user_agent"),
            (COOKIE, "agent\nInjected", "invalid_user_agent"),
        ]:
            with self.subTest(reason=reason):
                opener = Opener()
                output = execute(CONTEXT, cookie, user_agent=agent, opener=opener)
                self.assertEqual(output["reason"], reason)
                self.assertEqual(opener.calls, [])

    def test_invalid_proxy_is_reported_without_exposing_its_value(self):
        for proxy in ["socks5://synthetic-secret@proxy.invalid:1", "http://[synthetic-secret"]:
            with self.subTest(proxy=proxy):
                output = execute(CONTEXT, COOKIE, proxy=proxy)
                self.assertEqual(output["reason"], "invalid_proxy")
                self.assertNotIn("synthetic-secret", json.dumps(output))

    def test_transport_failure_is_bounded_and_not_retried(self):
        for error in [TimeoutError("synthetic-secret"), URLError("synthetic-secret"),
                      IncompleteRead(b"synthetic-secret", 30)]:
            with self.subTest(error=type(error).__name__):
                opener = Opener(error)
                output = execute(CONTEXT, COOKIE, opener=opener)
                self.assertEqual(output["reason"], "points_transport_error")
                self.assertEqual(len(opener.calls), 1)
                self.assertNotIn("synthetic-secret", json.dumps(output))

    def test_http_error_body_is_not_copied_and_stream_is_closed(self):
        stream = io.BytesIO(b"synthetic-secret")
        error = HTTPError("https://m.you.163.com", 403, "secret", {}, stream)
        output = execute(CONTEXT, COOKIE, opener=Opener(error))
        self.assertEqual(output["reason"], "authentication_rejected")
        self.assertTrue(stream.closed)
        self.assertNotIn("synthetic-secret", json.dumps(output))

    def test_redirect_is_rejected_without_forwarding_credentials(self):
        with self.assertRaisesRegex(QueryError, "unexpected_redirect"):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://other.invalid")
        output = execute(CONTEXT, COOKIE, opener=Opener(QueryError("unexpected_redirect")))
        self.assertEqual(output["reason"], "unexpected_redirect")

    def test_response_size_limits_close_stream_and_do_not_retry(self):
        for response, reason in [
            (Response(None, headers={"Content-Length": str(MAX_RESPONSE + 1)}), "response_too_large"),
            (Response(None, raw=b"x" * (MAX_RESPONSE + 1)), "response_too_large"),
            (Response(None, headers={"Content-Length": "bad"}), "invalid_response_length"),
            (Response(None, raw=b"<html>synthetic-secret</html>"), "invalid_json_response"),
        ]:
            with self.subTest(reason=reason):
                opener = Opener(response)
                output = execute(CONTEXT, COOKIE, opener=opener)
                self.assertEqual(output["reason"], reason)
                self.assertEqual(len(opener.calls), 1)
                self.assertTrue(response.closed)

    def test_no_mutation_operation_is_available(self):
        opener = Opener()
        client = Client(COOKIE, opener=opener)
        for path in ["/xhr/points/sign.json", "/xhr/points/receiveAll.json"]:
            with self.assertRaisesRegex(QueryError, "unsupported_operation"):
                client._request(path, "POST")
        self.assertEqual(opener.calls, [])


class YanxuanEntrypointTests(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]

    def invoke(self, runtime, *arguments):
        return subprocess.run(
            [sys.executable, str(self.root / "platforms/yanxuan/status.py"),
             "--runtime-root", runtime, *arguments],
            env={"PATH": os.environ["PATH"]}, capture_output=True, text=True, timeout=5,
        )

    def test_no_execute_has_no_network_or_latest_result(self):
        with tempfile.TemporaryDirectory() as runtime:
            child = self.invoke(runtime)
            self.assertEqual(child.returncode, 1, child.stderr)
            value = json.loads(child.stdout)
            self.assertEqual(value["reason"], "execution_not_requested")
            self.assertFalse((Path(runtime) / "results").exists())

    def test_missing_cookie_returns_one_structured_result(self):
        with tempfile.TemporaryDirectory() as runtime:
            child = self.invoke(runtime, "--execute")
            self.assertEqual(child.returncode, 1, child.stderr)
            value = json.loads(child.stdout)
            self.assertEqual(value["reason"], "missing_or_invalid_cookie")
            self.assertEqual(value["business"], {"points_query": "unknown"})
            self.assertEqual(value["platform"], "yanxuan")
            self.assertTrue((Path(runtime) / "results/yanxuan/default/latest.json").is_file())


if __name__ == "__main__":
    unittest.main()
