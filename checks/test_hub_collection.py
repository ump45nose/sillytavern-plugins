"""Report behavior checks; no production reads or Telegram sends."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import importlib.util
from io import StringIO
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "hub_collection_report", Path(__file__).resolve().parents[1] / "hermes/hub_collection_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)
NOW = datetime(2026, 10, 11, 8, 0, tzinfo=timezone.utc)


def snapshot():
    return {"checked_at": NOW.isoformat(), "sources": {"google": {"interval_seconds": 3600}},
            "latest_runs": {"google": {"source": "google", "status": "ok", "error": None,
                "started_at": (NOW - timedelta(minutes=20)).isoformat(),
                "ended_at": (NOW - timedelta(minutes=10)).isoformat()}}, "latest_finished_runs": {}}


class ReportTests(unittest.TestCase):
    def output(self, value, state="active"):
        output = StringIO()
        with patch.object(report, "load_snapshot", return_value=value), \
                patch.object(report, "service_state", return_value=state), redirect_stdout(output):
            self.assertEqual(report.main(), 0)
        return output.getvalue()

    def test_normal_empty_runs_and_historical_warnings_are_silent(self):
        value = snapshot()
        value["latest_runs"]["google"]["records"] = 0
        value["quality_warnings"] = [{"code": "historical_segment_invalid", "count": 25}]
        self.assertEqual(self.output(value), "")

    def test_disabled_push_and_unconfigured_sources_are_excluded(self):
        value = snapshot()
        value["sources"].update(health={"enabled": False}, finance={"collection_mode": "push"})
        issue = {"source": "health", "status": "failed", "count": 1, "ended_at": NOW.isoformat()}
        value["recent_issues"] = [issue, {**issue, "source": "finance"}, {**issue, "source": "retired"}]
        self.assertEqual(self.output(value), "")

    def test_recovered_failures_are_silent(self):
        value = snapshot()
        value["recent_issues"] = [{"source": "google", "status": "failed", "error": "RuntimeError",
                                  "count": 8, "ended_at": (NOW - timedelta(hours=1)).isoformat()}]
        self.assertEqual(self.output(value), "")

    def test_current_failure_is_not_duplicated(self):
        value = snapshot()
        reason = "Google OAuth 凭据已失效，需要重新授权"
        value["latest_runs"]["google"].update(status="failed", error=json.dumps({
            "type": "GoogleReadError", "reason": reason, "causes": ["verbose metadata"]}))
        value["recent_issues"] = [{**value["latest_runs"]["google"], "count": 3}]
        problems = report.collect_problems(value, NOW)
        self.assertEqual(problems, [("Google 日历 / Tasks", reason)])
        output = self.output(value)
        self.assertIn("- Google 日历 / Tasks：" + reason, output)
        for text in ("已恢复", "次", "GoogleReadError", "verbose metadata", "最近失败"):
            self.assertNotIn(text, output)

    def test_running_retry_does_not_clear_unresolved_failure(self):
        value = snapshot()
        value["latest_finished_runs"]["google"] = {
            **value["latest_runs"]["google"], "status": "failed", "error": "TimeoutError"}
        value["latest_runs"]["google"].update(status="running", error=None, ended_at=None)
        self.assertEqual(report.collect_problems(value, NOW), [("Google 日历 / Tasks", "采集请求超时")])
        value["latest_finished_runs"]["google"].update(status="ok", error=None)
        self.assertEqual(self.output(value), "")

    def test_success_clears_previous_failure(self):
        value = snapshot()
        value["latest_finished_runs"]["google"] = {
            **value["latest_runs"]["google"], "status": "failed", "error": "TimeoutError"}
        self.assertEqual(self.output(value), "")

    def test_partial_and_old_current_failure_are_reported(self):
        value = snapshot()
        value["latest_runs"]["google"].update(status="partial", error="segment_invalid")
        self.assertIn("片段校验失败", report.collect_problems(value, NOW)[0][1])
        value["latest_runs"]["google"].update(status="failed", ended_at=(NOW - timedelta(days=2)).isoformat())
        problems = report.collect_problems(value, NOW)
        self.assertEqual(len(problems), 1)
        self.assertIn("没有完成采集", problems[0][1])

    def test_stall_and_running_timeout_use_interval_and_floor(self):
        for interval, threshold in ((900, 3600), (3600, 10800)):
            for state in ("ok", "running"):
                with self.subTest(interval=interval, state=state):
                    value = snapshot()
                    value["sources"]["google"]["interval_seconds"] = interval
                    key = "started_at" if state == "running" else "ended_at"
                    value["latest_runs"]["google"]["status"] = state
                    value["latest_runs"]["google"][key] = (NOW - timedelta(seconds=threshold)).isoformat()
                    self.assertEqual(report.collect_problems(value, NOW), [])
                    value["latest_runs"]["google"][key] = (NOW - timedelta(seconds=threshold + 60)).isoformat()
                    self.assertEqual(len(report.collect_problems(value, NOW)), 1)

    def test_missing_run_and_inactive_service_are_reported(self):
        value = snapshot()
        value["latest_runs"] = {}
        self.assertIn("没有运行记录", self.output(value))
        self.assertIn("采集服务未运行", self.output(snapshot(), "inactive"))

    def test_old_recovered_and_future_failures_are_excluded(self):
        value = snapshot()
        row = {"source": "google", "status": "failed", "count": 1}
        value["recent_issues"] = [{**row, "ended_at": (NOW - timedelta(days=2)).isoformat()},
                                  {**row, "ended_at": (NOW + timedelta(hours=1)).isoformat()}]
        self.assertEqual(report.collect_problems(value, NOW), [])

    def test_probe_failure_emits_only_sanitized_alert(self):
        for exc in (RuntimeError("secret database URL"), subprocess.TimeoutExpired("docker", 60)):
            with self.subTest(exc=type(exc).__name__):
                output = StringIO()
                with patch.object(report, "load_snapshot", side_effect=exc), \
                        patch.object(report, "service_state", return_value="active"), redirect_stdout(output):
                    report.main()
                self.assertIn("无法读取", output.getvalue())
                self.assertNotIn("secret", output.getvalue())

    def test_error_details_cannot_leak_credentials(self):
        for error in ("https://secret:token@example.com", json.dumps({
                "reason": "Bearer secret-token"}), json.dumps({"reason": "refresh_token=secret"})):
            with self.subTest(error=error):
                value = snapshot()
                value["latest_runs"]["google"].update(status="failed", error=error)
                output = self.output(value)
                self.assertIn("具体原因未记录", output)
                self.assertNotIn("token", output)

    def test_long_diagnostics_are_concise(self):
        self.assertEqual(report.failure_reason(json.dumps({"reason": "a" * 500})), "a" * 160)


if __name__ == "__main__":
    unittest.main()
