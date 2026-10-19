import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "platforms" / "telegram" / "run.py"


class TelegramEntrypointTests(unittest.TestCase):
    def invoke(self, root, *args):
        return subprocess.run(
            [sys.executable, str(ENTRY), "--runtime-root", root, *args],
            env={"PATH": os.environ["PATH"]},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_task_declaration(self):
        from platforms.telegram.run import TASK

        self.assertEqual(TASK.platform, "telegram")
        self.assertTrue(TASK.browser)
        self.assertEqual(TASK.environment, frozenset({"TELEGRAM_CONFIG", "TELEGRAM_PROXY"}))

    def test_offline_entrypoint(self):
        with tempfile.TemporaryDirectory() as root:
            r = self.invoke(root, "--account", "tg-ai")
            self.assertEqual(r.returncode, 1)
            self.assertEqual(json.loads(r.stdout)["reason"], "execution_not_requested")
            self.assertFalse((Path(root) / "results").exists())

    def test_login_timeout_covers_qr_wait(self):
        import argparse
        from unittest import mock
        from platforms.telegram.run import TASK
        for given, expected in ((600.0, 900.0), (1200.0, 1200.0)):
            args = argparse.Namespace(login=True, status=False, timeout=given)
            with mock.patch.object(sys, "stdin", mock.Mock(isatty=lambda: True)):
                TASK.validate(argparse.ArgumentParser(), args)
            self.assertEqual(args.timeout, expected)
        args = argparse.Namespace(login=False, status=True, timeout=600.0)
        TASK.validate(argparse.ArgumentParser(), args)
        self.assertEqual(args.timeout, 600.0)

    def test_login_requires_terminal_and_excludes_status(self):
        with tempfile.TemporaryDirectory() as root:
            for args in (("--login",), ("--login", "--status")):
                r = self.invoke(root, "--execute", *args)
                self.assertEqual(r.returncode, 2)
                self.assertIn("--login requires an interactive terminal", r.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_status_without_profile_is_not_logged_in_per_account(self):
        with tempfile.TemporaryDirectory() as root:
            for account in ("tg-ai", "tg-nsfw"):
                r = self.invoke(root, "--account", account, "--execute", "--status")
                self.assertEqual(r.returncode, 1, r.stdout)
                out = json.loads(r.stdout)
                self.assertEqual((out["account"], out["reason"], out["business"]),
                                 (account, "not_logged_in", {"checkin": "blocked"}))
                latest = Path(root) / "results/telegram" / account / "latest.json"
                self.assertEqual(json.loads(latest.read_text())["account"], account)
                self.assertFalse((Path(root) / "state/telegram" / account / "browser").exists())


if __name__ == "__main__":
    unittest.main()
