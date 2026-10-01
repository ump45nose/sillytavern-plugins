from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from common.intervention_signal import create_checkpoint


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "signal.json"
        self.context = {
            "run_id": "fixture",
            "platform": "rewards",
            "account": "account1",
        }
        self.value = {
            "schema_version": 1,
            **self.context,
            "capability": "daily",
            "phase": "daily_cards",
            "kind": "captcha",
            "target": "https://rewards.bing.com/dashboard",
            "fingerprint": "a" * 64,
            "ttl_seconds": 300,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, value=None):
        self.path.write_text(json.dumps(value or self.value))
        return create_checkpoint(
            self.path,
            self.context,
            "activities",
            now=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )

    def test_safe_signal_creates_pending_not_grant(self):
        out = self.make()
        self.assertEqual(out["kind"], "captcha")
        self.assertNotIn("decision", out)
        self.assertEqual(out["resume_policy"], "readback_then_revalidate")

    def test_exact_identity(self):
        for key in ("run_id", "platform", "account"):
            with self.assertRaises(ValueError):
                self.make({**self.value, key: "other"})

    def test_unsupported_capability(self):
        with self.assertRaises(ValueError):
            self.make({**self.value, "capability": "claim"})

    def test_unhashable_discriminators_rejected(self):
        for key in ("capability", "kind"):
            for value in ([], {}, None):
                with self.assertRaises(ValueError):
                    self.make({**self.value, key: value})

    def test_no_query_or_unexpected_domain(self):
        for url in [
            "https://rewards.bing.com/?token=x",
            "http://rewards.bing.com/",
            "https://rewards.bing.com.evil.invalid/",
            "https://x@rewards.bing.com/",
            "https://rewards.bing.com/#secret",
        ]:
            with self.assertRaises(ValueError):
                self.make({**self.value, "target": url})

    def test_no_arbitrary_payload(self):
        with self.assertRaises(ValueError):
            self.make({**self.value, "html": "fixture"})

    def test_ttl_bounded(self):
        for ttl in (0, 901, True, "300"):
            with self.assertRaises(ValueError):
                self.make({**self.value, "ttl_seconds": ttl})

    def test_oversized(self):
        self.path.write_text(" " * 8193)
        with self.assertRaises(ValueError):
            create_checkpoint(self.path, self.context, "activities")


class SignalRunnerTests(unittest.TestCase):
    def test_child_signal_becomes_pending_checkpoint(self):
        import io
        import sys
        from unittest.mock import patch
        from common.runner import run
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
                self.assertEqual(run("rewards"), 1)
            report = json.loads(output.getvalue())
            self.assertEqual(report["reason"], "approval_required_captcha")
            request = json.loads(
                (Path(root) / "runs" / report["run_id"] / "checkpoint.json").read_text()
            )
            self.assertEqual(request["platform"], "rewards")
            self.assertEqual(request["account"], "default")
            self.assertNotIn("decision", request)
