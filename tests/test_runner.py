import json
import os
import signal
import time
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io
from common.model import atomic_json
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def test_original_platform_time_budgets(self):
        from importlib import import_module
        budgets = {name: import_module("platforms." + name + ".run").TASK.timeout
                   for name in ("smzdm", "v2ex", "aliyun", "laowang", "rewards", "epic")}

        self.assertEqual(
            budgets,
            {
                "smzdm": 180,
                "v2ex": 240,
                "aliyun": 480,
                "laowang": 360,
                "rewards": 7500,
                "epic": 1300,
            },
        )

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
            self.assertIn("unrecognized arguments", r.stderr)

    def test_missing_credentials_structured(self):
        with tempfile.TemporaryDirectory() as root:
            r = self.invoke("smzdm", root, "--execute")
            self.assertEqual(r.returncode, 1)
            self.assertEqual(json.loads(r.stdout)["reason"], "missing_session")

    def test_prior_checkin_does_not_skip_reward_reconciliation(self):
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
            fake = self.fake_adapter(root, "raise SystemExit(0)")
            r = self.invoke("smzdm", root, "--execute", "--node", str(fake))
            self.assertEqual(r.returncode, 3)
            self.assertEqual(json.loads(r.stdout)["reason"], "confirmed_fixture")
            self.assertTrue((Path(root) / "state/smzdm/default/invoked").exists())

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

    def test_cached_failure_does_not_replace_current_result(self):
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
            self.assertEqual(json.loads(r.stdout)["reason"], "missing_session")

    def test_rewards_full_requires_manifest_before_browser(self):
        with tempfile.TemporaryDirectory() as root:
            response = self.invoke("rewards", root, "--execute")
            self.assertEqual(response.returncode, 1)
            self.assertEqual(
                json.loads(response.stdout)["reason"], "capability_manifest_required"
            )

    def test_rewards_explicit_modes_remain_separate(self):
        with tempfile.TemporaryDirectory() as root:
            for mode in ("snapshot", "extra"):
                response = self.invoke("rewards", root, "--mode", mode, "--execute")
                self.assertEqual(response.returncode, 1)
                self.assertEqual(
                    json.loads(response.stdout)["execution_status"], "failed"
                )
                self.assertTrue(
                    (
                        Path(root) / "results/rewards/default" / mode / "latest.json"
                    ).exists()
                )
            self.assertFalse(
                (Path(root) / "results/rewards/default/full/latest.json").exists()
            )

    def fake_adapter(self, root, after):
        file = Path(root) / "fake-node"
        file.write_text(
            "#!" + sys.executable + "\n"
            "import json,os,pathlib,time\n"
            "c={k:os.environ['BENEFITS_'+k.upper()] for k in "
            "('run_id','platform','account','business_date')}\n"
            "r={'schema_version':1,**c,'execution_status':'ok',"
            "'reason':'confirmed_fixture','business':{'checkin':'complete','reward':'unknown'}}\n"
            "p=pathlib.Path(os.environ['BENEFITS_RESULT_PATH'])\n"
            "p.with_suffix('.tmp').write_text(json.dumps(r))\n"
            "p.with_suffix('.tmp').replace(p)\n"
            "(pathlib.Path(os.environ['BENEFITS_STATE_DIR'])/'invoked').write_text('yes')\n"
            + after
            + "\n"
        )
        file.chmod(0o700)
        return file

    def test_nonzero_after_confirmation_preserves_business(self):
        with tempfile.TemporaryDirectory() as root:
            fake = self.fake_adapter(root, "raise SystemExit(2)")
            response = self.invoke("smzdm", root, "--execute", "--node", str(fake))
            output = json.loads(response.stdout)
            self.assertEqual(response.returncode, 1)
            self.assertEqual(output["reason"], "process_failed_after_result")
            self.assertEqual(output["business"]["checkin"], "complete")
            cached = json.loads(
                (Path(root) / "results/smzdm/default/last-confirmed.json").read_text()
            )
            self.assertEqual(cached["business"]["checkin"], "complete")

    def test_timeout_preserves_business(self):
        with tempfile.TemporaryDirectory() as root:
            fake = self.fake_adapter(root, "time.sleep(30)")
            response = self.invoke(
                "smzdm", root, "--execute", "--node", str(fake), "--timeout", "2"
            )
            output = json.loads(response.stdout)
            self.assertEqual(response.returncode, 124)
            self.assertEqual(output["reason"], "deadline_exceeded")
            self.assertEqual(
                output["business"], {"checkin": "complete", "reward": "unknown"}
            )

    def test_interruption_preserves_business(self):
        with tempfile.TemporaryDirectory() as root:
            fake = self.fake_adapter(root, "time.sleep(30)")
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "platforms/smzdm/run.py"),
                    "--runtime-root",
                    root,
                    "--execute",
                    "--node",
                    str(fake),
                ],
                env={"PATH": os.environ["PATH"]},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            try:
                end = time.monotonic() + 3
                while not (Path(root) / "state/smzdm/default/invoked").exists():
                    if time.monotonic() >= end:
                        self.fail("fixture adapter did not start")
                    time.sleep(0.01)
                proc.send_signal(signal.SIGTERM)
                stdout, _ = proc.communicate(timeout=4)
                output = json.loads(stdout)
                self.assertEqual(output["reason"], "interrupted")
                self.assertEqual(output["business"]["checkin"], "complete")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_startup_io_failure_has_stdout_result(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "not-a-directory"
            file.write_text("fixture")
            response = self.invoke("smzdm", str(file))
            self.assertEqual(response.returncode, 1)
            self.assertEqual(
                json.loads(response.stdout)["reason"], "configuration_or_io_error"
            )
            self.assertNotIn("Traceback", response.stderr)

    def test_prior_unclean_browser_run_blocks_next_spawn(self):
        from common.containment import boot_id

        with tempfile.TemporaryDirectory() as root:
            atomic_json(
                Path(root) / "locks/browser-cleanup.json",
                {
                    "schema_version": 1,
                    "run_id": "interrupted",
                    "boot_id": boot_id(),
                    "launcher_pid": 999999,
                },
            )
            fake = self.fake_adapter(root, "raise SystemExit(0)")
            response = self.invoke("rewards", root, "--execute", "--node", str(fake))
            self.assertEqual(
                json.loads(response.stdout)["reason"], "browser_cleanup_unverified"
            )
            self.assertFalse((Path(root) / "state/rewards/default/invoked").exists())

    def test_cleanup_failure_dominates_intervention_preserving_business(self):
        from common.lifecycle import Outcome
        from common.runner import run
        from platforms.rewards.run import TASK

        for signal_result in ({"kind": "captcha"}, ValueError("invalid_signal")):
            with (
                self.subTest(signal=signal_result),
                tempfile.TemporaryDirectory() as root,
            ):

                def fake_supervise(argv, cwd, env, *args, **kwargs):
                    context = {
                        k: env["BENEFITS_" + k.upper()]
                        for k in ("run_id", "platform", "account", "business_date")
                    }
                    atomic_json(
                        env["BENEFITS_RESULT_PATH"],
                        {
                            "schema_version": 1,
                            **context,
                            "execution_status": "failed",
                            "reason": "full_in_progress",
                            "business": {
                                "daily": "complete",
                                "desktop_search": "unknown",
                            },
                        },
                    )
                    return Outcome(0)

                captured = io.StringIO()
                with (
                    patch.object(
                        sys, "argv", ["run.py", "--runtime-root", root, "--execute"]
                    ),
                    patch("common.runner.supervise", side_effect=fake_supervise),
                    patch(
                        "common.containment.BrowserScope.cleanup", return_value=False
                    ),
                    redirect_stdout(captured),
                ):
                    self.assertEqual(run(TASK), 1)
                output = json.loads(captured.getvalue())
                self.assertEqual(output["reason"], "browser_cleanup_unverified")
                self.assertEqual(
                    output["business"],
                    {"daily": "complete", "desktop_search": "unknown"},
                )
                self.assertTrue((Path(root) / "locks/browser-cleanup.json").exists())

    def test_cleanup_marker_io_failure_preserves_business(self):
        from common.lifecycle import Outcome
        from common.runner import run
        from platforms.rewards.run import TASK

        with tempfile.TemporaryDirectory() as root:

            def fake_supervise(argv, cwd, env, *args, **kwargs):
                context = {
                    k: env["BENEFITS_" + k.upper()]
                    for k in ("run_id", "platform", "account", "business_date")
                }
                atomic_json(
                    env["BENEFITS_RESULT_PATH"],
                    {
                        "schema_version": 1,
                        **context,
                        "execution_status": "ok",
                        "reason": "fixture",
                        "business": {"daily": "complete"},
                    },
                )
                return Outcome(0)

            captured = io.StringIO()
            with (
                patch.object(
                    sys, "argv", ["run.py", "--runtime-root", root, "--execute"]
                ),
                patch("common.runner.supervise", side_effect=fake_supervise),
                patch(
                    "common.containment.Path.unlink",
                    side_effect=PermissionError("fixture"),
                ),
                redirect_stdout(captured),
            ):
                self.assertEqual(run(TASK), 1)
            output = json.loads(captured.getvalue())
            self.assertEqual(output["reason"], "browser_cleanup_unverified")
            self.assertEqual(output["business"], {"daily": "complete"})

    def test_unsupported_pidfd_kernel_refuses_before_adapter_spawn(self):
        import errno
        from common.runner import run
        from platforms.rewards.run import TASK

        for code in (errno.ENOSYS, errno.EPERM):
            with self.subTest(errno=code), tempfile.TemporaryDirectory() as root:
                captured = io.StringIO()
                with (
                    patch.object(
                        sys, "argv", ["run.py", "--runtime-root", root, "--execute"]
                    ),
                    patch("common.runner.supervise") as spawn,
                    patch(
                        "common.containment.os.pidfd_open",
                        side_effect=OSError(code, "fixture"),
                    ),
                    redirect_stdout(captured),
                ):
                    self.assertEqual(run(TASK), 1)
                spawn.assert_not_called()
                self.assertEqual(
                    json.loads(captured.getvalue())["reason"],
                    "browser_containment_unavailable",
                )
                self.assertFalse((Path(root) / "locks/browser-cleanup.json").exists())
