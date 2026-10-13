import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EntryTests(unittest.TestCase):
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
