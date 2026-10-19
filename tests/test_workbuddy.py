"""Offline protocol, credential, and one-send recovery checks. No platform access."""
import io
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from common.model import atomic_json, validate
from platforms.workbuddy.adapter import execute
from platforms.workbuddy.client import BASES, Client, HTTP, MAX_BODY, parse_status, validate_chat
from platforms.workbuddy.login import Login, authorization_url, import_plaintext
from platforms.workbuddy.state import Credentials, Journal, WorkBuddyError, durable_json

CONTEXT = {"run_id": "offline", "platform": "workbuddy", "account": "cn-main", "business_date": "2026-10-19"}


def session(edition="cn"):
    return {"edition": edition, "access_token": "access-fixture", "refresh_token": "refresh-fixture",
            "uid": "uid-fixture", "domain": "www.workbuddy.ai" if edition == "intl" else ""}


def response(data, code=0, status=200):
    return status, json.dumps({"code": code, "data": data}).encode()


def point_rows(rows, total=None):
    data = {"Accounts": rows}
    if total is not None:
        data["TotalCount"] = total
    return response({"Response": {"Data": data}})


def points(value=100):
    return point_rows([{"PackageName": "fixture", "CapacityRemain": value, "CapacitySize": 200}], 1)


def state(checked=False, reward=None, active=True):
    data = {"active": active, "today_checked_in": checked, "streak_days": 2}
    if reward is not None:
        data["today_credit"] = reward
    return response(data)


def chat(content="1", done=True):
    return 200, ('data: ' + json.dumps({"choices": [{"delta": {"content": content}}]}) +
                 '\n\n' + ('data: [DONE]\n\n' if done else '')).encode()


class Transport:
    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def request(self, method, url, headers, payload=None):
        self.calls.append((method, url, dict(headers), payload))
        return self.handler(method, url, headers, payload)

    def count(self, suffix):
        return sum(url.endswith(suffix) for _, url, _, _ in self.calls)


class FakeCredentials:
    def __init__(self, edition="cn"):
        self.session, self.saved = session(edition), []

    def save(self, value):
        self.saved.append(dict(value))
        self.session = dict(value)


class DomesticTests(unittest.TestCase):
    def run_task(self, directory, handler, *, read_only=False, credentials=None):
        transport = Transport(handler)
        output = execute(CONTEXT, "cn", credentials or FakeCredentials(), directory,
                         transport=transport, read_only=read_only)
        validate(output, CONTEXT)
        return output, transport

    def test_already_signed_queries_balance_once_without_write(self):
        def handler(_, url, __, ___):
            return state(True, 100) if url.endswith("checkin-activity-status") else points(900)
        with tempfile.TemporaryDirectory() as directory:
            output, transport = self.run_task(directory, handler)
        self.assertEqual(output["business"], {"checkin": "complete", "reward": "complete", "balance": "complete"})
        self.assertEqual(transport.count("daily-checkin"), 0)
        self.assertEqual(transport.count("get-user-resource"), 1)
        self.assertEqual(output["details"]["metrics"]["balance"]["delta"], 0)

    def test_signed_without_actual_credit_does_not_invent_daily_reward(self):
        def handler(_, url, __, ___):
            if url.endswith("checkin-activity-status"):
                return response({"active": True, "today_checked_in": True, "daily_credit": 100})
            return points()
        with tempfile.TemporaryDirectory() as directory:
            output, _ = self.run_task(directory, handler)
        self.assertEqual(output["business"]["reward"], "unknown")
        self.assertIsNone(output["details"]["metrics"]["reward"]["current"])

    def test_activity_inactive_is_not_applicable(self):
        def handler(_, url, __, ___):
            return response({"active": False}) if url.endswith("checkin-activity-status") else points()
        with tempfile.TemporaryDirectory() as directory:
            output, transport = self.run_task(directory, handler)
        self.assertEqual(output["business"]["checkin"], "not_applicable")
        self.assertEqual(output["reason"], "activity_inactive")
        self.assertEqual(transport.count("daily-checkin"), 0)

    def test_submit_once_then_readback_and_persist_reward(self):
        signed = False
        def handler(_, url, __, ___):
            nonlocal signed
            if url.endswith("checkin-activity-status"):
                return state(signed)
            if url.endswith("daily-checkin"):
                signed = True
                return response({"success": True, "credit": 100})
            return points(200 if signed else 100)
        with tempfile.TemporaryDirectory() as directory:
            first, transport = self.run_task(directory, handler)
            second, again = self.run_task(directory, handler)
        self.assertEqual(first["business"]["checkin"], "complete")
        self.assertEqual(first["details"]["metrics"]["balance"]["delta"], 100)
        self.assertEqual(transport.count("daily-checkin"), 1)
        self.assertEqual(again.count("daily-checkin"), 0)
        self.assertEqual(second["details"]["metrics"]["reward"]["current"], 100)

    def test_timeout_after_server_commits_is_reconciled_without_replay(self):
        signed = False
        def handler(_, url, __, ___):
            nonlocal signed
            if url.endswith("checkin-activity-status"):
                return state(signed, 100 if signed else None)
            if url.endswith("daily-checkin"):
                signed = True
                raise WorkBuddyError("transport_error")
            return points()
        with tempfile.TemporaryDirectory() as directory:
            output, transport = self.run_task(directory, handler)
            recovered, again = self.run_task(directory, handler)
        self.assertEqual(output["business"]["checkin"], "complete")
        self.assertEqual(recovered["business"]["checkin"], "complete")
        self.assertEqual(transport.count("daily-checkin"), 1)
        self.assertEqual(again.count("daily-checkin"), 0)

    def test_pending_intent_survives_process_restart_and_day_change(self):
        def handler(_, url, __, ___):
            if url.endswith("checkin-activity-status"):
                return state(False)
            if url.endswith("daily-checkin"):
                raise WorkBuddyError("transport_error")
            return points()
        with tempfile.TemporaryDirectory() as directory:
            output, first = self.run_task(directory, handler)
            second, again = self.run_task(directory, handler)
            tomorrow = {**CONTEXT, "business_date": "2026-10-20"}
            self.assertEqual(Journal(tomorrow, directory, "cn", "uid-fixture").status, "unknown")
        self.assertEqual(output["business"]["checkin"], "unknown")
        self.assertEqual(second["reason"], "checkin_submission_unconfirmed")
        self.assertEqual(first.count("daily-checkin"), 1)
        self.assertEqual(again.count("daily-checkin"), 0)

    def test_unknown_status_and_auth_failure_do_not_write(self):
        for body in ({}, {"active": True}, {"today_checked_in": "maybe"}):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                output, transport = self.run_task(directory, lambda *args: response(body))
                self.assertEqual(output["business"]["checkin"], "unknown")
                self.assertEqual(transport.count("daily-checkin"), 0)

    def test_status_mode_never_signs(self):
        def handler(_, url, __, ___):
            return state(False) if url.endswith("checkin-activity-status") else points()
        with tempfile.TemporaryDirectory() as directory:
            output, transport = self.run_task(directory, handler, read_only=True)
        self.assertEqual(output["reason"], "checkin_not_requested")
        self.assertEqual(transport.count("daily-checkin"), 0)

    def test_failed_balance_after_checkin_preserves_confirmation(self):
        signed = False
        def handler(_, url, __, ___):
            nonlocal signed
            if url.endswith("checkin-activity-status"):
                return state(signed, 100 if signed else None)
            if url.endswith("daily-checkin"):
                signed = True
                return response({})
            if signed:
                raise WorkBuddyError("transport_error")
            return points()
        with tempfile.TemporaryDirectory() as directory:
            output, _ = self.run_task(directory, handler)
        self.assertEqual(output["business"]["checkin"], "complete")
        self.assertEqual(output["business"]["reward"], "complete")
        self.assertIsNone(output["details"]["metrics"]["balance"]["after"])
        self.assertIsNone(output["details"]["metrics"]["balance"]["delta"])


class InternationalTests(unittest.TestCase):
    def run_task(self, directory, transport, *, read_only=False):
        context = {**CONTEXT, "account": "intl-main"}
        output = execute(context, "intl", FakeCredentials("intl"), directory,
                         transport=transport, read_only=read_only)
        validate(output, context)
        return output

    def transport(self, active_response=None):
        def handler(_, url, __, ___):
            if url.endswith("get-user-resource"):
                return points()
            if url.endswith("conversations/v2"):
                return response({"id": "server-conversation"})
            return active_response or chat()
        return Transport(handler)

    def test_fixed_model_prompt_and_session_identifiers(self):
        transport = self.transport()
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_task(directory, transport)
            again = self.transport()
            self.run_task(directory, again)
        create = next(row for row in transport.calls if row[1].endswith("conversations/v2"))
        request = next(row for row in transport.calls if row[1].endswith("chat/completions"))
        _, url, headers, body = request
        events = json.loads(body["extra_vars"]["growthEvent"])
        self.assertEqual(url, "https://www.workbuddy.ai/v2/chat/completions")
        self.assertEqual(body["model"], "hy3")
        self.assertEqual(body["messages"][1]["content"][0]["text"], "<user_query> only print:1 </user_query>")
        self.assertEqual(headers["X-Conversation-ID"], "server-conversation")
        self.assertEqual(events[0]["id"], create[3]["sessionId"])
        self.assertEqual(events[0]["extra"]["rootRequestId"], headers["X-Conversation-Request-ID"])
        self.assertEqual(output["business"]["activity"], "complete")
        self.assertEqual(output["business"]["reward"], "unknown")
        self.assertEqual(again.count("chat/completions"), 0)
        self.assertEqual(again.count("conversations/v2"), 0)

    def test_increased_balance_is_not_attributed_as_active_reward(self):
        calls = 0
        def handler(_, url, __, ___):
            nonlocal calls
            if url.endswith("get-user-resource"):
                calls += 1
                return points(100 if calls == 1 else 200)
            if url.endswith("conversations/v2"):
                return response({"id": "conversation"})
            return chat()
        with tempfile.TemporaryDirectory() as directory:
            output = self.run_task(directory, Transport(handler))
        self.assertEqual(output["details"]["metrics"]["balance"]["delta"], 100)
        self.assertIsNone(output["details"]["metrics"]["reward"]["current"])
        self.assertEqual(output["business"]["reward"], "unknown")

    def test_failed_stream_persists_pending_and_is_not_resent(self):
        for answer in (chat(done=False), (200, b'data: {"error":{"code":14018}}\n\n'), (200, b'data: [DONE]\n\n')):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as directory:
                transport = self.transport(answer)
                output = self.run_task(directory, transport)
                again = self.transport()
                second = self.run_task(directory, again)
                self.assertEqual(output["business"]["activity"], "unknown")
                self.assertEqual(second["business"]["activity"], "unknown")
                self.assertEqual(again.count("chat/completions"), 0)

    def test_timeout_does_not_replay(self):
        def handler(_, url, __, ___):
            if url.endswith("get-user-resource"):
                return points()
            if url.endswith("conversations/v2"):
                return response({"id": "conversation"})
            raise WorkBuddyError("transport_error")
        with tempfile.TemporaryDirectory() as directory:
            first = Transport(handler)
            self.run_task(directory, first)
            second = self.transport()
            self.run_task(directory, second)
        self.assertEqual(first.count("chat/completions"), 1)
        self.assertEqual(second.count("chat/completions"), 0)

    def test_failed_completion_save_preserves_response_fact_and_pending_intent(self):
        original = Journal.set
        def fail_completion(journal, status, reward=None):
            if status == "complete":
                raise WorkBuddyError("action_state_write_failed")
            return original(journal, status, reward)
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Journal, "set", fail_completion):
                output = self.run_task(directory, self.transport())
            again = self.transport()
            self.run_task(directory, again)
        self.assertEqual(output["business"]["activity"], "complete")
        self.assertEqual(output["reason"], "action_state_write_failed")
        self.assertEqual(again.count("chat/completions"), 0)

    def test_status_only_and_registration_failure_do_not_send_chat(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = self.transport()
            self.run_task(directory, transport, read_only=True)
            self.assertEqual(transport.count("conversations/v2"), 0)
            self.assertEqual(transport.count("chat/completions"), 0)
        def fail(_, url, __, ___):
            return points() if url.endswith("get-user-resource") else response({}, code=12153)
        with tempfile.TemporaryDirectory() as directory:
            transport = Transport(fail)
            output = self.run_task(directory, transport)
            self.assertEqual(output["reason"], "authentication_invalid")
            self.assertEqual(transport.count("chat/completions"), 0)


class ClientTests(unittest.TestCase):
    def client(self, transport, edition="cn", save=lambda value: None):
        return Client(edition, session(edition), save, transport)

    def test_refresh_is_persisted_before_retry_and_uses_correct_source(self):
        for edition, source in (("cn", "workbuddy"), ("intl", "plugin")):
            saved = []
            def handler(_, url, headers, payload):
                if url.endswith("token/refresh"):
                    self.assertNotIn("Authorization", headers)
                    self.assertEqual(headers["X-Auth-Refresh-Source"], source)
                    return response({"accessToken": "new-access", "refreshToken": "new-refresh"})
                if headers["Authorization"] == "Bearer access-fixture":
                    return response({}, code=12153, status=401)
                self.assertEqual(saved[0]["refresh_token"], "new-refresh")
                return points()
            with self.subTest(edition=edition):
                transport = Transport(handler)
                self.assertEqual(self.client(transport, edition, saved.append).points(), 100)
                self.assertEqual(transport.count("token/refresh"), 1)

    def test_failed_credential_save_stops_retry_and_writes(self):
        def handler(_, url, __, ___):
            return response({"accessToken": "new"}) if url.endswith("token/refresh") else response({}, 12153, 401)
        def fail_save(value):
            raise WorkBuddyError("credential_write_failed")
        client = self.client(Transport(handler), save=fail_save)
        with self.assertRaisesRegex(WorkBuddyError, "credential_write_failed"):
            client.points()
        self.assertEqual(client.http.count("get-user-resource"), 1)

    def test_write_401_is_not_retried_or_refreshed(self):
        transport = Transport(lambda *args: response({}, 12153, 401))
        with self.assertRaisesRegex(WorkBuddyError, "authentication_invalid"):
            self.client(transport).checkin()
        self.assertEqual(len(transport.calls), 1)

    def test_html_auth_response_refreshes_only_reads(self):
        n = 0
        def handler(_, url, __, ___):
            nonlocal n
            if url.endswith("token/refresh"):
                return response({"accessToken": "new"})
            n += 1
            return (401, b'<html>unauthorized</html>') if n == 1 else points()
        self.assertEqual(self.client(Transport(handler)).points(), 100)

    def test_status_legacy_route_only_used_for_404(self):
        for status in (404, 403, 500):
            def handler(_, url, __, ___):
                return response({}, 10, status) if url.endswith("checkin-activity-status") else state(True)
            with self.subTest(status=status):
                transport = Transport(handler)
                if status == 404:
                    self.assertTrue(self.client(transport).status()["checked"])
                else:
                    with self.assertRaises(WorkBuddyError):
                        self.client(transport).status()
                self.assertEqual(transport.count("checkin-status"), int(status == 404))

    def test_balance_aggregates_cycle_and_legacy_and_fetches_pages(self):
        def handler(_, __, ___, payload):
            if payload["PageNumber"] == 1:
                return point_rows([{"CycleCapacityRemain": 700, "CycleCapacitySize": 1000}], 2)
            return point_rows([{"CapacityRemain": 200, "CapacitySize": 500}], 2)
        self.assertEqual(self.client(Transport(handler)).points(), 900)

    def test_capacity_reconciliation_matches_upstream_available_balance(self):
        rows = [{"CycleCapacityRemain": 1200, "CycleCapacitySize": 1000},
                {"CycleCapacityRemain": 700, "CycleCapacitySize": 1000, "CycleCapacityUsed": 400},
                {"CapacityRemain": -20, "CapacitySize": 100},
                {"CapacityRemain": 200, "CapacitySize": 100}]
        transport = Transport(lambda *args: point_rows(rows, 4))
        self.assertEqual(self.client(transport).points(), 1700)

    def test_balance_missing_or_incomplete_is_unknown(self):
        responses = [response({}), response({"Response": {"Data": {}}}),
                     point_rows([], 2), point_rows([{"PackageName": "unknown"}], 1)]
        for answer in responses:
            with self.subTest(answer=answer), self.assertRaises(WorkBuddyError):
                self.client(Transport(lambda *args: answer)).points()

    def test_balance_pagination_count_drift_and_limit(self):
        n = 0
        def drift(*args):
            nonlocal n
            n += 1
            return point_rows([{"CapacityRemain": 1}], 3 if n == 1 else 2)
        with self.assertRaisesRegex(WorkBuddyError, "balance_unconfirmed"):
            self.client(Transport(drift)).points()
        full = point_rows([{"CapacityRemain": 1}] * 100)
        transport = Transport(lambda *args: full)
        with self.assertRaisesRegex(WorkBuddyError, "balance_page_limit"):
            self.client(transport).points()
        self.assertEqual(len(transport.calls), 100)

    def test_response_parser_accepts_camel_case_and_zero_credit(self):
        self.assertEqual(parse_status({"Active": "true", "todayCheckedIn": 1,
            "todayCredit": 0, "streakDays": 3}),
            {"active": True, "checked": True, "reward": 0, "streak": 3})

    def test_stream_completion_errors_and_typed_content(self):
        validate_chat(chat()[1])
        validate_chat(json.dumps({"choices": [{"message": {"content": [{"type": "text", "text": "1"}]}}]}).encode())
        for raw in (b'', b'data: [DONE]\n\n', chat(done=False)[1],
                    b'data: {"error":{}}\n\n', b'event: error\ndata: {}\n\n',
                    chat()[1] + b'data: {"code":14018}\n\n'):
            with self.subTest(raw=raw), self.assertRaises(WorkBuddyError):
                validate_chat(raw)

    def test_http_redirect_is_not_followed_and_body_is_bounded(self):
        http = HTTP()
        fake = HTTPError("https://www.codebuddy.cn", 302, "redirect", {}, io.BytesIO(b'{}'))
        with patch.object(http.opener, "open", side_effect=fake):
            status, _ = http.request("POST", "https://www.codebuddy.cn/test", {"Authorization": "Bearer fixture"}, {})
            self.assertEqual(status, 302)
        fake = HTTPError("https://www.codebuddy.cn", 200, "ok", {}, io.BytesIO(b'x' * (MAX_BODY + 1)))
        with patch.object(http.opener, "open", side_effect=fake), self.assertRaisesRegex(WorkBuddyError, "response_too_large"):
            http.request("POST", "https://www.codebuddy.cn/test", {}, {})

    def test_incomplete_http_read_is_a_redacted_transport_error(self):
        http = HTTP()
        fake = HTTPError("https://www.codebuddy.cn", 200, "ok", {}, io.BytesIO())
        with patch.object(http.opener, "open", return_value=fake), patch.object(fake, "read", side_effect=IncompleteRead(b'private-partial-body')):
            with self.assertRaisesRegex(WorkBuddyError, "transport_error") as caught:
                http.request("POST", "https://www.codebuddy.cn/test", {}, {})
            self.assertNotIn("private-partial-body", str(caught.exception))


class AuthAndStateTests(unittest.TestCase):
    def test_credentials_rotation_is_atomic_private_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            durable_json(path, session())
            credentials = Credentials(path, "cn")
            credentials.save({**credentials.session, "access_token": "rotated", "refresh_token": "rotated-refresh"})
            self.assertEqual(Credentials(path, "cn").session["refresh_token"], "rotated-refresh")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(WorkBuddyError, "session_edition_mismatch"):
                Credentials(path, "intl")
            path.chmod(0o644)
            with self.assertRaisesRegex(WorkBuddyError, "private_credentials_permissions"):
                Credentials(path, "cn")

    def test_journal_binds_account_uid_edition_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(CONTEXT, directory, "cn", "uid-fixture")
            journal.set("pending")
            for context, edition, uid in ((CONTEXT, "cn", "another-user"),
                ({**CONTEXT, "account": "another"}, "cn", "uid-fixture"), (CONTEXT, "intl", "uid-fixture")):
                with self.subTest(context=context, edition=edition, uid=uid), self.assertRaisesRegex(WorkBuddyError, "invalid_action_state"):
                    Journal(context, directory, edition, uid)
            journal.path.write_text('not json')
            with self.assertRaisesRegex(WorkBuddyError, "invalid_action_state"):
                Journal(CONTEXT, directory, "cn", "uid-fixture")

    def test_login_pending_then_token_and_account_use_same_product(self):
        for edition in ("cn", "intl"):
            n = 0
            base = BASES[edition][0]
            auth_url = ("https://www.workbuddy.ai/login" if edition == "intl" else "https://www.codebuddy.cn/login") + "?state=fixture"
            def handler(method, url, headers, payload):
                nonlocal n
                self.assertTrue(url.startswith(base))
                if "/auth/state?" in url:
                    self.assertIn("platform=" + ("workbuddy-ai" if edition == "intl" else "CLI"), url)
                    return response({"state": "fixture", "authUrl": auth_url})
                if "/auth/token?" in url:
                    n += 1
                    return response({}, code=11217) if n == 1 else response({"accessToken": "access", "refreshToken": "refresh"})
                self.assertEqual(headers["Authorization"], "Bearer access")
                return response({"uid": "uid"})
            with self.subTest(edition=edition):
                login = Login(edition, Transport(handler))
                self.assertEqual(login.start(), auth_url)
                with self.assertRaisesRegex(WorkBuddyError, "authorization_pending"):
                    login.poll()
                self.assertEqual(login.poll()["edition"], edition)

    def test_login_auth_rejection_is_not_pending(self):
        for status in (401, 403, 404, 429):
            transport = Transport(lambda *args: response({}, code=10, status=status))
            login = Login("intl", transport)
            login.state = "fixture"
            with self.subTest(status=status), self.assertRaises(WorkBuddyError) as caught:
                login.poll()
            self.assertNotEqual(caught.exception.reason, "authorization_pending")

    def test_authorization_url_rejects_cross_product_and_non_https(self):
        for url in ("javascript:alert(1)", "http://www.workbuddy.ai/login", "https://www.workbuddy.ai.evil.test/login",
                    "https://user@www.workbuddy.ai/login", "https://www.codebuddy.cn/login"):
            with self.subTest(url=url), self.assertRaisesRegex(WorkBuddyError, "untrusted_authorization_url"):
                authorization_url(url, "intl")

    def test_plaintext_client_import_and_encrypted_rejection(self):
        value = {"auth": {"accessToken": "access", "refreshToken": "refresh", "domain": "www.workbuddy.ai"},
                 "account": {"uid": "uid", "enterpriseId": None}}
        self.assertEqual(import_plaintext(value, "intl")["uid"], "uid")
        with self.assertRaisesRegex(WorkBuddyError, "session_edition_mismatch"):
            import_plaintext(value, "cn")
        value["auth"]["accessToken"] = {"$wbEncrypted": "fixture"}
        with self.assertRaisesRegex(WorkBuddyError, "encrypted_session_requires_client"):
            import_plaintext(value, "intl")

    def test_offline_entrypoints_and_missing_session(self):
        root = Path(__file__).resolve().parents[1]
        environment = {"PATH": os.environ["PATH"]}
        with tempfile.TemporaryDirectory() as directory:
            for edition in ("cn", "intl"):
                command = [sys.executable, str(root / "platforms/workbuddy/run.py"), "--runtime-root", directory, "--edition", edition]
                child = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=5)
                self.assertEqual(child.returncode, 1)
                self.assertEqual(json.loads(child.stdout)["reason"], "execution_not_requested")
                child = subprocess.run(command + ["--execute"], env=environment, capture_output=True, text=True, timeout=5)
                self.assertEqual(child.returncode, 1)
                self.assertEqual(json.loads(child.stdout)["reason"], "missing_session")


if __name__ == "__main__":
    unittest.main()
