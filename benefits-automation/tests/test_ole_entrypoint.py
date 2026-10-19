import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OleEntrypointTests(unittest.TestCase):
    def invoke(self, runtime, *arguments, environment=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "platforms/ole/run.py"),
             "--runtime-root", runtime, "--account", "test", *arguments],
            cwd=ROOT, env={"PATH": os.environ["PATH"], **(environment or {})}, capture_output=True,
            text=True, timeout=5,
        )

    def test_no_execute_has_no_credentials_or_node_dependency(self):
        with tempfile.TemporaryDirectory() as runtime:
            out = self.invoke(runtime, "--node", "/nonexistent/node")
            self.assertEqual(out.returncode, 1)
            row = json.loads(out.stdout)
            self.assertEqual(row["platform"], "ole")
            self.assertEqual(row["reason"], "execution_not_requested")
            self.assertFalse((Path(runtime) / "results").exists())

    def test_missing_config_is_structured_and_does_not_require_shared_code_client(self):
        with tempfile.TemporaryDirectory() as runtime:
            out = self.invoke(runtime, "--execute")
            self.assertEqual(out.returncode, 1, out.stderr)
            row = json.loads(out.stdout)
            self.assertEqual(row["reason"], "missing_configuration")
            self.assertEqual(row["business"]["checkin"], "blocked")
            latest = Path(runtime) / "results/ole/test/latest.json"
            self.assertEqual(json.loads(latest.read_text())["run_id"], row["run_id"])
            self.assertEqual(latest.stat().st_mode & 0o777, 0o600)

    def test_launcher_publishes_confirmed_sign_and_distinguishes_unknown_balance(self):
        for balance, expected_exit in [(123, 0), (None, 3)]:
            with self.subTest(balance=balance), tempfile.TemporaryDirectory() as runtime:
                private = Path(runtime) / "ole.json"
                private.write_text(json.dumps({"wechat": {
                    "url": "http://127.0.0.1:8000", "token": "synthetic-token", "account": "test-ref"
                }}))
                private.chmod(0o600)
                node = Path(runtime) / "mock-node.cjs"
                node.write_text(
                    "#!/usr/bin/env node\n"
                    "const path=require('node:path');\n"
                    "const adapter=require(process.argv[2]);\n"
                    "const {State,configurationIdentity}=require(path.join(path.dirname(process.argv[2]),'state.cjs'));\n"
                    "const config=adapter.readConfig(process.env.OLE_CONFIG);\n"
                    "const state=new State(process.env.BENEFITS_STATE_DIR,process.env.BENEFITS_ACCOUNT,"
                    "process.env.BENEFITS_BUSINESS_DATE,configurationIdentity(config.wechat));\n"
                    "state.saveSession({session_id:'synthetic-session',openid:'merchant-openid',shop_code:null});\n"
                    "global.fetch=async()=>new Response(JSON.stringify({state_code:200,data:{"
                    "sign_of_day:'Y',total_integral:" + json.dumps(balance) + "}}));\n"
                    "adapter.main();\n"
                )
                node.chmod(0o700)
                out = self.invoke(runtime, "--execute", "--node", str(node),
                                  environment={"OLE_CONFIG": str(private)})
                self.assertEqual(out.returncode, expected_exit, out.stderr)
                row = json.loads(out.stdout)
                self.assertEqual(row["execution_status"], "ok")
                self.assertEqual(row["business"]["checkin"], "complete")
                self.assertEqual(row["business"]["balance"], "complete" if balance is not None else "unknown")
                self.assertEqual(row["details"]["metrics"]["balance"]["current"], balance)


if __name__ == "__main__":
    unittest.main()
