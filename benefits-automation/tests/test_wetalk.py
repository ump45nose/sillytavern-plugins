"""Offline launcher/adapter contract, including real Node with a controlled transport."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is required for WeTalk")
class WetalkEntryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wetalk-entry-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "credentials.json"
        self.responses = self.root / "responses.json"
        self.calls = self.root / "calls.jsonl"
        self.responses.write_text("[]")
        self.config.write_text(json.dumps({
            "params": {"email": "fixture@example.test", "token": "synthetic-private-token"},
            "headers": {"User-Agent": "fixture", "Authorization": "synthetic-private-auth"},
        }))
        self.config.chmod(0o600)
        preload = self.root / "fixture.cjs"
        preload.write_text(
            "const fs=require('node:fs');\n"
            f"const rows=JSON.parse(fs.readFileSync({json.dumps(str(self.responses))},'utf8'));\n"
            "globalThis.fetch=async (url,options)=>{\n"
            " const target=new URL(url);\n"
            " if(target.origin!=='https://api.wetalkapp.com')throw Error('unexpected origin');\n"
            f" fs.appendFileSync({json.dumps(str(self.calls))},JSON.stringify({{path:target.pathname,method:options.method}})+'\\n');\n"
            " const row=rows.shift();if(!row)throw Error('unexpected request');\n"
            " if(row.error)throw Error('private URL in native error: '+url);\n"
            " return new Response(JSON.stringify(row.payload),{status:row.status||200});\n"
            "};\n"
        )
        self.wrapper = self.root / "fixture-node"
        self.wrapper.write_text(
            f"#!{sys.executable}\nimport os,sys\n"
            f"os.execv({NODE!r},[{NODE!r},'--require',{str(preload)!r},*sys.argv[1:]])\n"
        )
        self.wrapper.chmod(0o700)

    def invoke(self, *arguments, credentials=True):
        env = {"PATH": os.environ["PATH"]}
        if credentials:
            env["WETALK_CONFIG"] = str(self.config)
        return subprocess.run([
            sys.executable, str(ROOT / "platforms/wetalk/run.py"),
            "--runtime-root", str(self.root / "runtime"), "--account", "account1",
            "--node", str(self.wrapper), *arguments,
        ], env=env, capture_output=True, text=True, timeout=10)

    def script(self, *rows):
        self.responses.write_text(json.dumps(list(rows)))

    @staticmethod
    def balance(amount, allowed, reason=""):
        return {"payload": {"retcode": 0, "result": {
            "balance": amount, "isallowcheckin": allowed, "notallowcheckinreason": reason,
        }}}

    def test_default_entry_is_offline_even_with_a_configuration(self):
        process = self.invoke()
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(json.loads(process.stdout)["reason"], "execution_not_requested")
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.root / "runtime/results").exists())

    def test_missing_configuration_is_a_structured_failure(self):
        process = self.invoke("--execute", credentials=False)
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(json.loads(process.stdout)["reason"], "missing_configuration")
        self.assertFalse(self.calls.exists())

    def test_read_only_eligibility_is_incomplete_without_a_write(self):
        self.script(self.balance("1.5", True))
        process = self.invoke("--execute", "--status")
        self.assertEqual(process.returncode, 3, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output["business"], {"checkin": "incomplete", "balance": "complete"})
        self.assertEqual(output["details"]["metrics"]["balance"]["current"], 1.5)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)

    def test_real_adapter_and_launcher_sign_recover_and_preserve_private_boundaries(self):
        self.script(self.balance(1, True), {"error": True}, self.balance(2, False, "今日已签到"))
        process = self.invoke("--execute")
        self.assertEqual(process.returncode, 0, process.stderr)
        output = json.loads(process.stdout)
        self.assertEqual(output["reason"], "checkin_recovered")
        self.assertEqual(output["details"]["metrics"]["balance"]["delta"], 1)
        saved = self.root / "runtime/results/wetalk/account1/latest.json"
        self.assertEqual(json.loads(saved.read_text())["run_id"], output["run_id"])
        self.assertEqual([json.loads(line)["path"] for line in self.calls.read_text().splitlines()],
                         ["/app/queryBalanceAndBonus", "/app/checkIn", "/app/queryBalanceAndBonus"])
        self.script(self.balance(2, False, "今日已签到"))
        repeated = self.invoke("--execute")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.calls.read_text().splitlines()), 4)
        for file in (self.root / "runtime").rglob("*"):
            if file.is_file():
                text = file.read_text(errors="replace")
                for private in ("fixture@example.test", "synthetic-private-token", "synthetic-private-auth"):
                    self.assertNotIn(private, text, str(file))
        self.assertNotIn("synthetic-private-token", process.stdout + process.stderr)

    def test_unexplained_unavailability_is_partial_not_false_success(self):
        self.script(self.balance(1, False, "当前不可领取"))
        process = self.invoke("--execute")
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(json.loads(process.stdout)["business"]["checkin"], "blocked")

    def test_insecure_config_never_reaches_transport(self):
        self.config.chmod(0o644)
        process = self.invoke("--execute")
        self.assertEqual(process.returncode, 1, process.stderr)
        self.assertEqual(json.loads(process.stdout)["reason"], "private_configuration_unreadable")
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
