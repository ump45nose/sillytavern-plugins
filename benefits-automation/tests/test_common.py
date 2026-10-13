import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from common.model import result, validate, atomic_json, read_result, progress
from common.locks import Lease, Busy
from common.lifecycle import LogSink, supervise


class CommonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = dict(
            run_id="r", platform="smzdm", account="test", business_date="2026-10-01"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_result_identity_and_schema(self):
        r = result(self.context)
        validate(r, self.context)
        for key in self.context:
            bad = dict(r)
            bad[key] = "old"
            with self.assertRaises(ValueError):
                validate(bad, self.context)
        with self.assertRaises(ValueError):
            validate({**r, "cookie": "secret"}, self.context)

    def test_atomic_permissions_size(self):
        p = self.root / "result.json"
        atomic_json(p, result(self.context))
        self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(read_result(p, self.context)["run_id"], "r")
        p.write_bytes(b" " * 65537)
        with self.assertRaises(ValueError):
            read_result(p, self.context)

    def test_progress_unknowns(self):
        for a, b in [
            (None, None),
            (None, 100),
            (0, 0),
            (-1, 10),
            ("x", 2),
            (1, float("nan")),
            (True, 1),
        ]:
            self.assertEqual(progress(a, b), "unknown")
        self.assertEqual(progress(1, 2), "incomplete")
        self.assertEqual(progress(2, 2), "complete")
        self.assertEqual(progress(None, None, "not_applicable"), "not_applicable")

    def test_lock_inode_and_contention(self):
        p = self.root / "browser.lock"
        with Lease(p):
            inode = p.stat().st_ino
            with self.assertRaises(Busy):
                with Lease(p, 0.05):
                    pass
        with Lease(p):
            self.assertEqual(p.stat().st_ino, inode)

    def test_redaction_chunk_boundaries_and_limit(self):
        p = self.root / "log"
        sink = LogSink(p, ["secret-value"], 100)
        sink.feed(b"a sec")
        sink.feed(b"ret-value b")
        sink.feed(b"x" * 1000)
        sink.close()
        content = p.read_bytes()
        self.assertNotIn(b"secret-value", content)
        self.assertIn(b"[REDACTED]", content)
        self.assertEqual(len(content), 100)

    def supervise(self, code, timeout=2):
        sink = LogSink(self.root / "log", limit=1024)
        try:
            return supervise(
                [sys.executable, "-c", code],
                self.root,
                {"PATH": os.environ["PATH"]},
                timeout,
                sink,
                grace=0.2,
            )
        finally:
            sink.close()

    def test_normal_exit(self):
        self.assertEqual(self.supervise('print("ok")').returncode, 0)

    def test_nonzero(self):
        self.assertEqual(self.supervise("raise SystemExit(3)").returncode, 3)

    def test_spawn_error(self):
        sink = LogSink(self.root / "log")
        try:
            self.assertTrue(
                supervise(["/nonexistent"], self.root, {}, 2, sink).spawn_error
            )
        finally:
            sink.close()

    def test_timeout_ignores_term(self):
        start = time.monotonic()
        r = self.supervise(
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(20)"
        )
        self.assertTrue(r.timed_out)
        self.assertLess(time.monotonic() - start, 3)

    def test_flood_bounded(self):
        r = self.supervise('import os\nwhile True:os.write(1,b"x"*65536)')
        self.assertTrue(r.timed_out)
        self.assertEqual((self.root / "log").stat().st_size, 1024)

    def test_exited_leader_descendant_terminated(self):
        pidfile = self.root / "pid"
        code = f'import subprocess,sys; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);open({str(pidfile)!r},"w").write(str(p.pid))'
        r = self.supervise(code)
        self.assertEqual(r.returncode, 0)
        pid = int(pidfile.read_text())
        stat = Path(f"/proc/{pid}/stat")
        self.assertTrue(not stat.exists() or stat.read_text().split()[2] == "Z")

    def test_sigterm_supervisor(self):
        script = self.root / "supervisor.py"
        script.write_text(
            "from common.lifecycle import *\nfrom pathlib import Path\nimport os\nsink=LogSink("
            + repr(str(self.root / "childlog"))
            + ')\nr=supervise(["'
            + sys.executable
            + '","-c","import time;time.sleep(30)"],"/tmp",dict(os.environ),20,sink,grace=.2)\nsink.close()\nprint(r.interrupted,flush=True)\n'
        )
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
            stdout=subprocess.PIPE,
        )
        time.sleep(0.3)
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=3)
        self.assertIn(b"True", out)


if __name__ == "__main__":
    unittest.main()


class LeaseCrashTests(unittest.TestCase):
    def test_inherited_lease_survives_launcher_exit(self):
        # The dedicated child retains fd when the lock owner exits abnormally.
        with tempfile.TemporaryDirectory() as root:
            lock = Path(root) / "lease"
            pidfile = Path(root) / "child"
            script = f"""from common.locks import Lease
import subprocess,sys,os
with Lease({str(lock)!r}) as lease:
 p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],pass_fds=(lease.fd,))
 open({str(pidfile)!r},'w').write(str(p.pid))
 os._exit(0)
"""
            subprocess.run([sys.executable, "-c", script], check=True)
            pid = int(pidfile.read_text())
            try:
                with self.assertRaises(Busy):
                    with Lease(lock):
                        pass
            finally:
                os.kill(pid, signal.SIGKILL)
            end = time.monotonic() + 2
            while time.monotonic() < end:
                try:
                    with Lease(lock):
                        break
                except Busy:
                    time.sleep(0.02)
            else:
                self.fail("lease not released after child termination")
