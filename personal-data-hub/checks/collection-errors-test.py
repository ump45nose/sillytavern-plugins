"""Safe failure records and isolated collection diagnostics; no upstream requests."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from sqlalchemy import select

from personal_data_hub import cli, runner
from personal_data_hub.collection_errors import error_detail, isolated_error, IsolatedSourceError
from personal_data_hub.contracts import Batch, canonical
from personal_data_hub.google_read import GoogleReadError
from personal_data_hub.storage import Store, runs


class ErrorTests(unittest.TestCase):
    def test_known_reasons_are_readable(self):
        self.assertIn("分页未推进", error_detail(RuntimeError("google_pagination_stalled"))["reason"])
        self.assertEqual(error_detail(GoogleReadError("Google OAuth 凭据已失效，需要重新授权")),
                         {"type": "GoogleReadError", "reason": "Google OAuth 凭据已失效，需要重新授权"})
        self.assertIn("网络连接失败", error_detail(GoogleReadError("Google OAuth 刷新失败：URLError"))["reason"])
        self.assertIn("请求超时", error_detail(GoogleReadError("Google API 读取失败：TimeoutError"))["reason"])
        self.assertIn("HTTP 403", error_detail(GoogleReadError("Google API 读取失败：HTTP 403"))["reason"])

    def test_untrusted_exception_text_is_never_saved(self):
        for kind in (RuntimeError, GoogleReadError, PermissionError, FileNotFoundError, TimeoutError, URLError):
            with self.subTest(kind=kind):
                self.assertNotIn("private-token", canonical(error_detail(kind("Bearer private-token"))))
        detail = error_detail(HTTPError("https://private-token", 503, "private-token", {}, None))
        self.assertEqual(detail["reason"], "来源接口请求失败（HTTP 503）")

    def test_exception_group_retains_safe_causes(self):
        detail = error_detail(ExceptionGroup("private-token", [TimeoutError("secret"), PermissionError("secret")]))
        self.assertEqual(len(detail["causes"]), 2)
        self.assertIn("请求超时", detail["reason"])
        self.assertIn("权限不足", detail["reason"])
        self.assertNotIn("private-token", canonical(detail))

    def test_isolated_error_preserves_diagnostics_not_stderr(self):
        detail = error_detail(GoogleReadError("Google API 读取失败：HTTP 403"))
        stderr = "noisy private-token\n" + canonical({"collection_error": detail}) + "\nother output"
        self.assertEqual(error_detail(isolated_error(stderr)), detail)
        self.assertNotIn("private-token", canonical(error_detail(isolated_error("private-token\n[]\nnull"))))

    def test_export_cli_emits_safe_error_without_traceback(self):
        stdout, stderr = StringIO(), StringIO()
        with patch("sys.argv", ["hub", "export-source", "google"]), \
                patch.object(cli, "configuration", return_value={"sources": {"google": {}}}), \
                patch.object(runner, "adapter", side_effect=GoogleReadError("Google OAuth 凭据已失效，需要重新授权")), \
                patch.object(cli, "store_from") as store, redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(json.loads(stderr.getvalue())["collection_error"]["type"], "GoogleReadError")
        self.assertNotIn("Traceback", stderr.getvalue())
        store.assert_not_called()

    def test_failed_run_is_completed_and_success_clears_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store("sqlite:///" + str(Path(tmp) / "test.sqlite"), str(Path(tmp) / "assets"))
            with patch.object(runner, "adapter", side_effect=TimeoutError("private-token")):
                with self.assertRaises(TimeoutError):
                    runner.run(store, "example", {"adapter": "files"})
            with store.engine.connect() as connection:
                row = connection.execute(select(runs)).mappings().one()
            self.assertEqual(row["status"], "failed")
            self.assertIsNotNone(row["ended_at"])
            self.assertEqual(json.loads(row["error"]), {"type": "TimeoutError", "reason": "采集请求超时"})
            with patch.object(runner, "adapter") as adapter:
                adapter.return_value.collect.return_value = [Batch()]
                runner.run(store, "example", {"adapter": "files"})
            with store.engine.connect() as connection:
                rows = connection.execute(select(runs).order_by(runs.c.started_at)).mappings().all()
            self.assertEqual(rows[-1]["status"], "ok")
            self.assertIsNone(rows[-1]["error"])
            store.engine.dispose()

    def test_isolated_failed_run_records_child_reason(self):
        detail = error_detail(GoogleReadError("Google API 读取失败：HTTP 403"))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store("sqlite:///" + str(Path(tmp) / "test.sqlite"), str(Path(tmp) / "assets"))
            result = subprocess.CompletedProcess([], 1, "", canonical({"collection_error": detail}))
            with patch("subprocess.run", return_value=result):
                with self.assertRaises(IsolatedSourceError):
                    runner.run(store, "google", {"adapter": "google", "run_as": "root"})
            with store.engine.connect() as connection:
                row = connection.execute(select(runs)).mappings().one()
            self.assertEqual(row["status"], "failed")
            self.assertEqual(json.loads(row["error"]), detail)
            store.engine.dispose()


if __name__ == "__main__":
    unittest.main()
