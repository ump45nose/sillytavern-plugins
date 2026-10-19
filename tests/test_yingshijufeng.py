import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class YingshijufengEntrypointTests(unittest.TestCase):
    def invoke(self, runtime, *arguments, config=None):
        environment = {"PATH": os.environ["PATH"]}
        if config:
            environment["YINGSHIJUFENG_CONFIG"] = str(config)
        return subprocess.run(
            [sys.executable, str(ROOT / "platforms/yingshijufeng/run.py"),
             "--runtime-root", str(runtime), *arguments],
            env=environment, capture_output=True, text=True, timeout=8,
        )

    def test_offline_entrypoint_does_not_read_configuration_or_load_node(self):
        with tempfile.TemporaryDirectory() as runtime:
            completed = self.invoke(runtime, "--node", "/not/a/node", config="/missing/private.json")
            self.assertEqual(completed.returncode, 1)
            output = json.loads(completed.stdout)
            self.assertEqual(output["reason"], "execution_not_requested")
            self.assertEqual(output["platform"], "yingshijufeng")
            self.assertFalse((Path(runtime) / "results").exists())

    def test_missing_configuration_is_a_structured_failure(self):
        with tempfile.TemporaryDirectory() as runtime:
            completed = self.invoke(runtime, "--execute")
            output = json.loads(completed.stdout)
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(output["reason"], "missing_configuration")
            self.assertEqual(output["business"]["checkin"], "unknown")
            self.assertEqual(completed.stderr, "")

    def test_status_flag_is_offline_without_execute(self):
        with tempfile.TemporaryDirectory() as runtime:
            completed = self.invoke(runtime, "--status", "--node", "/not/a/node")
            self.assertEqual(json.loads(completed.stdout)["reason"], "execution_not_requested")

    def test_readable_credential_file_is_rejected_without_leaking_content(self):
        with tempfile.TemporaryDirectory() as runtime:
            config = Path(runtime) / "private.json"
            config.write_text(json.dumps({"wechat": {"url": "http://localhost:8000",
                "token": "do-not-print-me", "account": "private-account"}}))
            config.chmod(0o644)
            completed = self.invoke(runtime, "--execute", config=config)
            self.assertEqual(completed.returncode, 1)
            self.assertEqual(json.loads(completed.stdout)["reason"], "private_file_invalid")
            self.assertNotIn("do-not-print-me", completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
