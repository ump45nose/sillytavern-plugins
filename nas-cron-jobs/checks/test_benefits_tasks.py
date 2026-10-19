"""Exercise configured job identity through launch, delivery and exception report."""

from contextlib import redirect_stdout
from datetime import datetime
import importlib.util
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hermes"))


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


runner = module("benefits_job_runner", "hermes/benefits_native_runner.py")
report = module("benefits_job_report", "hermes/reports/benefits-automation/daily_report.py")
summary = module("benefits_job_summary", "hermes/benefits_daily_summary.py")


class JobTests(unittest.TestCase):
    def test_international_activity_summary_preserves_unknown_reward_and_observed_balance(self):
        text = summary.describe("workbuddy", {"execution_status": "ok",
            "business": {"activity": "complete", "reward": "unknown", "balance": "complete"},
            "details": {"metrics": {"balance": {"unit": "points", "current": 350, "delta": 0}}}})
        self.assertIn("部分完成", text)
        self.assertIn("活跃请求已完成", text)
        self.assertIn("奖励未确认", text)
        self.assertIn("余额 350分", text)
        self.assertNotIn("奖励 0", text)

    def test_workbuddy_editions_use_one_provider_and_distinct_delivery_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = {"workbuddy-" + edition: {"platform": "workbuddy", "label": edition,
                "account": "workbuddy-" + edition, "python": sys.executable,
                "timeout": 120, "arguments": ["--edition", edition]} for edition in ("cn", "intl")}
            config = {"repository": str(ROOT.parent / "benefits-automation"),
                "runtime_root": str(root / "runtime"), "timezone": "Asia/Shanghai",
                "node": "node", "browser_cache": "/unused-browser", "tasks": tasks}
            config_file = root / "benefits-deployment.json"
            config_file.write_text(json.dumps(config))
            calls = []

            def execute(argv, **kwargs):
                calls.append(argv)
                self.assertTrue(argv[1].endswith("/platforms/workbuddy/run.py"))
                account = argv[argv.index("--account") + 1]
                row = {"schema_version": 1, "run_id": "run-" + account,
                    "platform": "workbuddy", "account": account,
                    "business_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                    "execution_status": "ok", "reason": "confirmed",
                    "business": {"checkin": "complete"}, "details": {"metrics": {}, "items": []}}
                return subprocess.CompletedProcess(argv, 0, json.dumps(row))

            with patch.object(runner, "CONFIG", config_file), \
                    patch.object(runner.subprocess, "run", side_effect=execute), redirect_stdout(StringIO()):
                runner.main("workbuddy-cn")
                runner.main("workbuddy-intl")
            for edition in ("cn", "intl"):
                row = json.loads((root / "runtime/delivery" / ("workbuddy-" + edition + ".json")).read_text())
                self.assertEqual(row["platform"], "workbuddy")
                self.assertEqual(row["account"], "workbuddy-" + edition)
                self.assertEqual(row["execution_status"], "ok")
            self.assertEqual(len(calls), 2)
            self.assertFalse((root / "runtime/delivery/workbuddy.json").exists())

    def test_report_uses_configured_tasks_and_verifies_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "runtime/delivery"
            delivery.mkdir(parents=True)
            tasks = {"workbuddy-cn": {"label": "国内版", "platform": "workbuddy", "account": "cn"},
                "glados": {"label": "GLaDOS", "account": "main"},
                "ole": {"label": "Olé", "enabled": False}}
            (root / "benefits-deployment.json").write_text(json.dumps({"tasks": tasks}))
            row = {"platform": "workbuddy", "account": "another-account", "business_date": "2026-10-19",
                "execution_status": "ok", "business": {"checkin": "complete"}, "reason": "confirmed"}
            (delivery / "workbuddy-cn.json").write_text(json.dumps(row))
            with patch.object(report, "DELIVERY_ROOT", delivery):
                text = report.build_report("2026-10-19")
            self.assertIn("国内版：结果账号与配置不一致", text)
            self.assertIn("GLaDOS：未取得当日结果", text)
            self.assertNotIn("Olé", text)
            self.assertNotIn("Steam", text)

    def test_shared_code_service_failure_is_one_actionable_issue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "runtime/delivery"
            delivery.mkdir(parents=True)
            tasks = {"ole": {"label": "Olé"}, "yingshijufeng": {"label": "影视飓风"}}
            (root / "benefits-deployment.json").write_text(json.dumps({"tasks": tasks}))
            for name in tasks:
                row = {"platform": name, "business_date": "2026-10-19", "execution_status": "failed",
                    "business": {"checkin": "unknown"}, "reason": "wechat_code_authentication_invalid"}
                (delivery / (name + ".json")).write_text(json.dumps(row))
            with patch.object(report, "DELIVERY_ROOT", delivery):
                text = report.build_report("2026-10-19")
            self.assertEqual(text.count("\n- "), 1)
            self.assertIn("微信取码服务认证失效（影响：Olé、影视飓风）", text)


if __name__ == "__main__":
    unittest.main()
