"""Only fake/local processes; browser launch tests use a fake executable."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from common.containment import BrowserScope, ContainmentError, boot_id, inspect_marker
from common.lifecycle import LogSink, supervise
from common.locks import Lease
from common.model import atomic_json

ROOT = Path(__file__).resolve().parents[1]


class ContainmentTests(unittest.TestCase):
    def test_exited_child_is_reaped_without_requiring_pidfd(self):
        scope = BrowserScope("unused", "fixture")
        with (patch("common.containment.children", side_effect=[[123], []]),
              patch("common.containment.os.waitpid", return_value=(123, 0)) as wait,
              patch("common.containment.os.pidfd_open", side_effect=ProcessLookupError) as open_fd):
            self.assertTrue(scope.cleanup())
        wait.assert_called_once_with(123, os.WNOHANG)
        open_fd.assert_not_called()

    def test_unconfirmed_ownership_is_logged_without_signalling(self):
        records = []
        scope = BrowserScope("unused", "fixture", report=records.append)
        with (patch("common.containment.children", return_value=[123]),
              patch("common.containment.os.waitpid", side_effect=ChildProcessError),
              patch("common.containment.os.pidfd_open") as open_fd):
            self.assertFalse(scope.cleanup())
        self.assertEqual(records, [{"event": "browser_cleanup_failed", "reason": "ownership_unconfirmed", "pid": 123}])
        open_fd.assert_not_called()

    def test_does_not_adopt_or_kill_unrelated_existing_child(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        try:
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaisesRegex(ContainmentError, "containment_in_use"):
                    with BrowserScope(Path(root) / "pending", "fixture"):
                        self.fail("scope should not enter")
                self.assertIsNone(proc.poll())
        finally:
            proc.kill()
            proc.wait()

    def test_pending_marker_requires_verified_ownership_not_age_or_dead_pid(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "pending"
            atomic_json(
                marker,
                {
                    "schema_version": 1,
                    "run_id": "old",
                    "boot_id": boot_id(),
                    "launcher_pid": 999999,
                },
            )
            with self.assertRaisesRegex(ContainmentError, "cleanup_unverified"):
                with BrowserScope(marker, "new"):
                    self.fail("must not enter")
            self.assertEqual(inspect_marker(marker)["run_id"], "old")

    def test_previous_boot_is_safe_to_recover(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "pending"
            atomic_json(
                marker,
                {
                    "schema_version": 1,
                    "run_id": "old",
                    "boot_id": "00000000-0000-0000-0000-000000000000",
                    "launcher_pid": 999999,
                },
            )
            with BrowserScope(marker, "new") as scope:
                self.assertEqual(inspect_marker(marker)["run_id"], "new")
            self.assertTrue(scope.cleanup_verified)
            self.assertFalse(marker.exists())

    def test_unverified_cleanup_keeps_marker(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "pending"
            with patch.object(BrowserScope, "cleanup", return_value=False):
                with BrowserScope(marker, "fixture"):
                    pass
            self.assertTrue(marker.exists())

    def test_capability_failure_does_not_enter_or_clear_pending(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "pending"
            with patch("common.containment.ctypes.CDLL") as library:
                library.return_value.prctl.return_value = -1
                with self.assertRaisesRegex(
                    ContainmentError, "containment_unavailable"
                ):
                    with BrowserScope(marker, "fixture"):
                        self.fail("must not enter")
            self.assertFalse(marker.exists())

    def run_detached(self, driver, root, timeout=2):
        marker = root / "pending"
        sink = LogSink(root / "log")
        try:
            with Lease(root / "browser.lock") as lease:
                with BrowserScope(marker, "fixture") as scope:
                    outcome = supervise(
                        driver,
                        root,
                        dict(os.environ),
                        timeout,
                        sink,
                        [lease.fd],
                        grace=0.2,
                    )
                self.assertTrue(scope.cleanup_verified)
            self.assertFalse(marker.exists())
            with Lease(root / "browser.lock"):
                pass
            return outcome
        finally:
            sink.close()

    def test_detached_descendant_reaped_after_adapter_exits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile = root / "pid"
            code = (
                "import subprocess,sys;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],start_new_session=True);"
                f"open({str(pidfile)!r},'w').write(str(p.pid))"
            )
            outcome = self.run_detached([sys.executable, "-c", code], root)
            self.assertEqual(outcome.returncode, 0)
            self.assertFalse(Path(f"/proc/{pidfile.read_text()}").exists())

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_real_pinned_launchers_fake_browser_survives_adapter_kill_only_until_cleanup(
        self,
    ):
        # Uses installed, pinned launch code, not real Firefox/Chromium or a site.
        for package, engine in [
            ("laowang/node_modules/playwright-firefox", "firefox"),
        ]:
            with (
                self.subTest(engine=engine),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                dependency = ROOT / "platforms" / package
                if not dependency.exists():
                    self.skipTest(f"{dependency.name} is not installed")
                pidfile = root / "fake-browser-pid"
                fake = root / "fake-browser"
                fake.write_text(
                    "#!" + sys.executable + "\nimport os,signal,time\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    f"open({str(pidfile)!r},'w').write(str(os.getpid()))\n"
                    "time.sleep(60)\n"
                )
                fake.chmod(0o700)
                driver = root / "driver.cjs"
                driver.write_text(
                    f"const browser = require({json.dumps(str(dependency))}).{engine};\n"
                    f"browser.launch({{executablePath:{json.dumps(str(fake))},headless:true,timeout:30000}}).catch(()=>{{}});\n"
                    f"const t=setInterval(()=>{{if(require('node:fs').existsSync({json.dumps(str(pidfile))})){{clearInterval(t);while(true){{}}}}}},10);\n"
                )
                try:
                    outcome = self.run_detached(["node", str(driver)], root, timeout=3)
                    self.assertTrue(outcome.timed_out)
                    self.assertEqual(outcome.returncode, -signal.SIGKILL)
                    self.assertTrue(
                        pidfile.exists(), "pinned launcher must start the fake browser"
                    )
                    self.assertFalse(Path(f"/proc/{pidfile.read_text()}").exists())
                finally:
                    # Only this test's known fake child; protect against regressions.
                    if pidfile.exists():
                        try:
                            os.kill(int(pidfile.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_sigkill_launcher_leaves_marker_and_next_run_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "launcher.py"
            marker = root / "pending"
            script.write_text(
                "from common.containment import BrowserScope\nimport time\n"
                f"with BrowserScope({str(marker)!r}, 'fixture'): time.sleep(30)\n"
            )
            proc = subprocess.Popen(
                [sys.executable, str(script)],
                env={**os.environ, "PYTHONPATH": str(ROOT)},
            )
            try:
                end = time.monotonic() + 3
                while not marker.exists():
                    if time.monotonic() > end:
                        self.fail("marker was not created")
                    time.sleep(0.01)
                proc.kill()
                proc.wait(timeout=2)
                with self.assertRaisesRegex(ContainmentError, "cleanup_unverified"):
                    with BrowserScope(marker, "next"):
                        self.fail("must not enter")
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_corrupt_same_length_boot_id_never_recovers(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "pending"
            atomic_json(
                marker,
                {
                    "schema_version": 1,
                    "run_id": "old",
                    "boot_id": "x" * 36,
                    "launcher_pid": 999999,
                },
            )
            with self.assertRaisesRegex(ContainmentError, "cleanup_unverified"):
                with BrowserScope(marker, "new"):
                    self.fail("invalid boot ID is not reboot evidence")
            self.assertEqual(json.loads(marker.read_text())["boot_id"], "x" * 36)

    def test_orphan_after_launcher_sigkill_cannot_overlap_next_browser_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "fake-node"
            pidfile = root / "owned-pids.json"
            fake.write_text(
                "#!" + sys.executable + "\n"
                "import json,os,subprocess,sys,time\n"
                "browser=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                "start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                f"open({str(pidfile)!r},'w').write(json.dumps({{'adapter':os.getpid(),'browser':browser.pid}}))\n"
                "time.sleep(60)\n"
            )
            fake.chmod(0o700)
            argv = [
                sys.executable,
                str(ROOT / "platforms/laowang/run.py"),
                "--runtime-root",
                str(root),
                "--execute",
                "--node",
                str(fake),
            ]
            launcher = subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            fds = {}
            try:
                end = time.monotonic() + 3
                while not pidfile.exists():
                    if time.monotonic() > end:
                        self.fail("fake adapter did not start")
                    time.sleep(0.01)
                owned = json.loads(pidfile.read_text())
                fds = {key: os.pidfd_open(pid) for key, pid in owned.items()}
                launcher.kill()
                launcher.wait(timeout=2)
                signal.pidfd_send_signal(fds["adapter"], signal.SIGKILL)
                # Its inherited lease closes on death, but the detached browser
                # remains. The persisted marker must block replacement execution.
                end = time.monotonic() + 2
                while time.monotonic() < end:
                    path = Path(f"/proc/{owned['adapter']}/stat")
                    if not path.exists() or path.read_text().split()[2] == "Z":
                        break
                    time.sleep(0.01)
                next_run = subprocess.run(
                    argv, capture_output=True, text=True, timeout=4
                )
                self.assertEqual(
                    json.loads(next_run.stdout)["reason"], "browser_cleanup_unverified"
                )
                signal.pidfd_send_signal(fds["browser"], 0)
            finally:
                if launcher.poll() is None:
                    launcher.kill()
                    launcher.wait()
                for fd in fds.values():
                    try:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finally:
                        os.close(fd)
