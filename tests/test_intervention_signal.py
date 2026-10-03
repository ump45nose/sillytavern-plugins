"""An obstacle file is delivery information, not a scheduler approval bridge."""
import json
from pathlib import Path
import tempfile
import unittest

class SignalRunnerTests(unittest.TestCase):
    def test_runner_preserves_reason_without_creating_approval_checkpoint(self):
        import io
        import sys
        from unittest.mock import patch
        from common.runner import run
        from platforms.rewards.run import TASK
        from common.lifecycle import Outcome
        from common.model import result, atomic_json

        with tempfile.TemporaryDirectory() as root:

            def fake(argv, cwd, env, timeout, sink, lease_fds, **kwargs):
                context = {
                    k: env["BENEFITS_" + k.upper()]
                    for k in ("run_id", "platform", "account", "business_date")
                }
                result_path = Path(env["BENEFITS_RESULT_PATH"])
                atomic_json(result_path, result(context, reason="human_required"))
                signal = {
                    "schema_version": 1,
                    "run_id": context["run_id"],
                    "platform": context["platform"],
                    "account": context["account"],
                    "capability": "snapshot",
                    "phase": "readback",
                    "kind": "captcha",
                    "target": "https://rewards.bing.com/dashboard",
                    "fingerprint": "a" * 64,
                    "ttl_seconds": 300,
                }
                atomic_json(result_path.parent / "obstacle-signal.json", signal)
                return Outcome(1)

            output = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "run.py",
                        "--runtime-root",
                        root,
                        "--mode",
                        "snapshot",
                        "--execute",
                    ],
                ),
                patch("common.runner.supervise", side_effect=fake),
                patch.object(sys, "stdout", output),
            ):
                self.assertEqual(run(TASK), 1)
            report = json.loads(output.getvalue())
            self.assertEqual(report["reason"], "human_required")
            self.assertFalse((Path(root) / "runs" / report["run_id"] / "checkpoint.json").exists())
