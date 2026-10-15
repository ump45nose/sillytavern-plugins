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
from personal_data_hub.collection_errors import error_detail
from personal_data_hub.contracts import Batch, canonical
from personal_data_hub.storage import Store, runs


class ErrorTests(unittest.TestCase):

    def test_untrusted_exception_text_is_never_saved(self):
        for kind in (RuntimeError, PermissionError, FileNotFoundError, TimeoutError, URLError):
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



    def test_failed_run_is_completed_and_success_clears_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store("sqlite:///" + str(Path(tmp) / "test.sqlite"), str(Path(tmp) / "assets"))
            with patch.object(runner, "adapter", side_effect=TimeoutError("private-token")):
                with self.assertRaises(TimeoutError):
                    runner.run(store, "example", {"adapter": "skysight"})
            with store.engine.connect() as connection:
                row = connection.execute(select(runs)).mappings().one()
            self.assertEqual(row["status"], "failed")
            self.assertIsNotNone(row["ended_at"])
            self.assertEqual(json.loads(row["error"]), {"type": "TimeoutError", "reason": "采集请求超时"})
            with patch.object(runner, "adapter") as adapter:
                adapter.return_value.collect.return_value = [Batch()]
                runner.run(store, "example", {"adapter": "skysight"})
            with store.engine.connect() as connection:
                rows = connection.execute(select(runs).order_by(runs.c.started_at)).mappings().all()
            self.assertEqual(rows[-1]["status"], "ok")
            self.assertIsNone(rows[-1]["error"])
            store.engine.dispose()



if __name__ == "__main__":
    unittest.main()
