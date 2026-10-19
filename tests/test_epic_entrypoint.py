import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class EntryTests(unittest.TestCase):
    def test_failure_before_workflow_preserves_private_safe_diagnostic(self):
        from platforms.epic import adapter
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "epic.json"
            config.write_text("{}")
            output = Path(directory) / "result.json"
            env = {"BENEFITS_RUN_ID": "fixture", "BENEFITS_PLATFORM": "epic",
                "BENEFITS_ACCOUNT": "one", "BENEFITS_BUSINESS_DATE": "2026-10-19",
                "BENEFITS_STATE_DIR": directory, "BENEFITS_RESULT_PATH": str(output),
                "EPIC_CONFIG": str(config)}
            cases = [(RuntimeError("private-token-and-password"), "native_configuration_or_browser_error")]
            try:
                from playwright.async_api import TimeoutError as BrowserTimeout
                cases.append((BrowserTimeout("private-token-and-password"), "browser_timeout"))
            except ImportError:
                pass
            for error, reason in cases:
                stream = io.StringIO()
                with self.subTest(reason=reason), patch.dict(os.environ, env), patch(
                        "platforms.epic.native.execute", side_effect=error), contextlib.redirect_stdout(stream):
                    self.assertEqual(adapter.main(), 2)
                self.assertEqual(json.loads(output.read_text())["reason"], reason)
                diagnostic = json.loads(stream.getvalue())
                self.assertEqual(diagnostic["event"], "epic_native_error")
                self.assertEqual(diagnostic["type"], type(error).__name__)
                self.assertTrue(diagnostic["frames"])
                self.assertNotIn("private-token", stream.getvalue())

    def test_missing_native_config_does_not_load_old_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            env = {
                **os.environ,
                "BENEFITS_RUN_ID": "fixture",
                "BENEFITS_PLATFORM": "epic",
                "BENEFITS_ACCOUNT": "one",
                "BENEFITS_BUSINESS_DATE": "2026-10-01",
                "BENEFITS_RESULT_PATH": str(output),
                "EPIC_UPSTREAM_DIR": "/missing/old-runtime",
            }
            completed = subprocess.run(
                [sys.executable, str(ROOT / "platforms/epic/adapter.py")],
                env=env,
                capture_output=True,
                timeout=5,
            )
            self.assertEqual(completed.returncode, 2)
            value = json.loads(output.read_text())
            self.assertEqual(
                value["reason"], "native_configuration_or_browser_error"
            )
            self.assertNotEqual(value.get("execution"), "ok")


if __name__ == "__main__":
    unittest.main()
