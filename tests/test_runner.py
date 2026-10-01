import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from common.model import atomic_json
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def invoke(self, platform, runtime, *args):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "platforms" / platform / "run.py"),
                "--runtime-root",
                runtime,
                *args,
            ],
            env={"PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_six_offline_entrypoints(self):
        with tempfile.TemporaryDirectory() as root:
            for platform in ["smzdm", "v2ex", "aliyun", "laowang", "epic", "rewards"]:
                r = self.invoke(platform, root)
                self.assertEqual(r.returncode, 1)
                self.assertEqual(
                    json.loads(r.stdout)["reason"], "execution_not_requested"
                )
            self.assertFalse((Path(root) / "results").exists())

    def test_reject_status_other_platform(self):
        with tempfile.TemporaryDirectory() as root:
            r = self.invoke("smzdm", root, "--execute", "--status")
            self.assertEqual(r.returncode, 2)
            self.assertIn("only by Laowang", r.stderr)

    def test_missing_credentials_structured(self):
        with tempfile.TemporaryDirectory() as root:
            r = self.invoke("smzdm", root, "--execute")
            self.assertEqual(r.returncode, 1)
            self.assertEqual(json.loads(r.stdout)["reason"], "missing_session")

    def test_daily_dedup_preserves_reward_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "results/smzdm/default/last-confirmed.json"
            atomic_json(
                path,
                {
                    "schema_version": 1,
                    "run_id": "previous",
                    "execution_status": "ok",
                    "reason": "fixture",
                    "platform": "smzdm",
                    "account": "default",
                    "business_date": datetime.now(ZoneInfo("Asia/Shanghai"))
                    .date()
                    .isoformat(),
                    "business": {"checkin": "complete", "reward": "unknown"},
                },
            )
            r = self.invoke("smzdm", root, "--execute")
            self.assertEqual(r.returncode, 3)
            self.assertEqual(
                json.loads(r.stdout)["reason"], "daily_checkin_already_confirmed"
            )

    def test_account_lock_busy(self):
        from common.locks import Lease

        with tempfile.TemporaryDirectory() as root:
            with Lease(Path(root) / "locks/smzdm.default.lock"):
                r = self.invoke("smzdm", root)
                self.assertEqual(r.returncode, 75)

    def test_cross_platform_browser_lock(self):
        from common.locks import Lease

        with tempfile.TemporaryDirectory() as root:
            with Lease(Path(root) / "locks/browser.lock"):
                for p in ["laowang", "rewards", "epic"]:
                    self.assertEqual(self.invoke(p, root).returncode, 75)

    def test_malformed_cache_does_not_crash(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "results/smzdm/default/last-confirmed.json"
            for business in (None, [], {"checkin": []}):
                atomic_json(
                    path,
                    {
                        "schema_version": 1,
                        "run_id": "old",
                        "platform": "smzdm",
                        "account": "default",
                        "business_date": datetime.now(ZoneInfo("Asia/Shanghai"))
                        .date()
                        .isoformat(),
                        "execution_status": "ok",
                        "reason": "fixture",
                        "business": business,
                    },
                )
                r = self.invoke("smzdm", root, "--execute")
                self.assertEqual(r.returncode, 1)
                self.assertEqual(json.loads(r.stdout)["reason"], "missing_session")

    def test_cached_failed_reward_stays_failed(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "results/smzdm/default/last-confirmed.json"
            atomic_json(
                path,
                {
                    "schema_version": 1,
                    "run_id": "old",
                    "platform": "smzdm",
                    "account": "default",
                    "business_date": datetime.now(ZoneInfo("Asia/Shanghai"))
                    .date()
                    .isoformat(),
                    "execution_status": "failed",
                    "reason": "reward_readback_failed",
                    "business": {"checkin": "complete", "reward": "unknown"},
                },
            )
            r = self.invoke("smzdm", root, "--execute")
            self.assertEqual(r.returncode, 1)
            self.assertEqual(json.loads(r.stdout)["execution_status"], "failed")
