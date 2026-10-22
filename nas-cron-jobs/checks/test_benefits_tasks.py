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
    def setUp(self):
        # These production entrypoints run separately and both own a common package.
        modules = patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        for name in list(sys.modules):
            if name == "common" or name.startswith("common."):
                sys.modules.pop(name)

    def test_external_task_never_launches_but_still_reports_its_returned_result(self):
        manifest = json.loads((ROOT / "hermes/manifest.json").read_text())["profile_scripts"]
        schedules = json.loads((ROOT / "hermes/schedules.json").read_text())
        self.assertNotIn("benefits_epic.py", manifest)
        self.assertNotIn("benefits-epic", {row["name"] for row in schedules})
        self.assertFalse((ROOT / "hermes/benefits_epic.py").exists())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "runtime/delivery"
            delivery.mkdir(parents=True)
            config = root / "benefits-deployment.json"
            config.write_text(json.dumps({"tasks": {"epic": {
                "label": "Epic 免费游戏（Mac）", "account": "default", "executor": "external"}}}))
            path = delivery / "epic.json"
            returned = {"platform": "epic", "account": "default", "business_date": "2026-10-22",
                        "execution_status": "failed", "reason": "store_assets_access_denied",
                        "business": {"claim": "unknown"}}
            path.write_text(json.dumps(returned))
            before = path.read_bytes()
            with patch.object(runner, "CONFIG", config), \
                    patch.object(runner.subprocess, "run") as launch, redirect_stdout(StringIO()):
                self.assertEqual(runner.main("epic"), 0)
            launch.assert_not_called()
            self.assertEqual(path.read_bytes(), before)
            with patch.object(report, "DELIVERY_ROOT", delivery):
                self.assertIn("Epic 免费游戏（Mac）：商店资源被拒绝访问", report.build_report("2026-10-22"))

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
                history = root / "runtime/runs" / row["run_id"] / "result.json"
                self.assertEqual(json.loads(history.read_text()), row)
            self.assertEqual(len(calls), 2)
            self.assertFalse((root / "runtime/delivery/workbuddy.json").exists())

    def test_launcher_failures_and_busy_attempts_preserve_history_and_replace_old_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "benefits-deployment.json"
            config_file.write_text(json.dumps({
                "repository": str(ROOT.parent / "benefits-automation"),
                "runtime_root": str(root / "runtime"), "timezone": "Asia/Shanghai",
                "node": "node", "browser_cache": "/unused-browser", "tasks": {
                    "glados": {"label": "GLaDOS", "account": "main", "python": sys.executable,
                               "timeout": 120}}}))
            row = {"schema_version": 1, "run_id": "successful-run", "platform": "glados",
                "account": "main", "business_date": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(),
                "execution_status": "ok", "reason": "checkin_confirmed", "business": {"checkin": "complete"},
                "details": {"metrics": {}, "items": []}}
            outputs = [subprocess.CompletedProcess([], 0, json.dumps(row)),
                FileNotFoundError("runtime missing"), subprocess.CompletedProcess([], 0, "[]"),
                subprocess.CompletedProcess([], 0, json.dumps({**row, "run_id": "../../outside"})),
                subprocess.CompletedProcess([], 75, json.dumps({**row, "run_id": "busy-run",
                    "execution_status": "busy", "reason": "lock_busy", "business": {"checkin": "unknown"}}))]
            with patch.object(runner, "CONFIG", config_file), \
                    patch.object(runner.subprocess, "run", side_effect=outputs), redirect_stdout(StringIO()):
                for expected in ("ok", "failed", "failed", "failed", "busy"):
                    runner.main("glados")
                    latest = json.loads((root / "runtime/delivery/glados.json").read_text())
                    self.assertEqual(latest["execution_status"], expected)
                    saved = root / "runtime/runs" / latest["run_id"] / "result.json"
                    self.assertEqual(json.loads(saved.read_text()), latest)
                    self.assertIsNotNone(datetime.fromisoformat(latest["started_at"]).tzinfo)
                    self.assertGreaterEqual(latest["duration_ms"], 0)
            histories = list((root / "runtime/runs").glob("*/result.json"))
            self.assertEqual(len(histories), 5)
            self.assertEqual(json.loads((root / "runtime/runs/successful-run/result.json").read_text())["execution_status"], "ok")
            self.assertFalse((root / "outside").exists())

    def test_new_platform_success_and_expected_international_reward_unknown_are_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "runtime/delivery"
            delivery.mkdir(parents=True)
            labels = {"glados": "GLaDOS", "yingshijufeng": "影视飓风", "ole": "Olé", "rainyun": "雨云",
                      "workbuddy-cn": "WorkBuddy 国内版", "workbuddy-intl": "WorkBuddy 国际版"}
            tasks = {key: {"label": label, "account": key, **({"platform": "workbuddy"}
                     if key.startswith("workbuddy-") else {})} for key, label in labels.items()}
            (root / "benefits-deployment.json").write_text(json.dumps({"tasks": tasks}))
            for key, task in tasks.items():
                row = {"platform": task.get("platform", key), "account": key, "business_date": "2026-10-19",
                       "execution_status": "ok", "reason": "checkin_confirmed", "business": {"checkin": "complete"}}
                (delivery / (key + ".json")).write_text(json.dumps(row))
            with patch.object(report, "DELIVERY_ROOT", delivery):
                self.assertEqual(report.build_report("2026-10-19"), "")
                row.update(platform="workbuddy", reason="activity_sent_reward_unconfirmed",
                           business={"checkin": "not_applicable", "activity": "complete",
                                     "reward": "unknown", "balance": "complete"})
                (delivery / "workbuddy-intl.json").write_text(json.dumps(row))
                self.assertEqual(report.build_report("2026-10-19"), "")

    def test_expected_workbuddy_reward_unknown_does_not_hide_other_problems(self):
        row = {"platform": "workbuddy", "business_date": "2026-10-21", "execution_status": "ok",
               "reason": "activity_sent_reward_unconfirmed", "business": {
                   "checkin": "not_applicable", "activity": "complete", "reward": "unknown", "balance": "complete"}}
        self.assertIsNone(report.issue_for("workbuddy", row, "2026-10-21"))
        cases = [
            {"execution_status": "failed"},
            {"reason": "authentication_invalid"},
            {"business_date": "2026-10-20"},
            {"platform": "another"},
            *({"business": {**row["business"], name: "unknown"}} for name in ("activity", "balance")),
            {"business": {name: state for name, state in row["business"].items() if name != "balance"}},
            {"business": {**row["business"], "checkin": "incomplete"}},
        ]
        for changed in cases:
            with self.subTest(changed=changed):
                self.assertIsNotNone(report.issue_for("workbuddy", {**row, **changed}, "2026-10-21"))

    def test_silent_workbuddy_result_still_verifies_configured_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "runtime/delivery"
            delivery.mkdir(parents=True)
            (root / "benefits-deployment.json").write_text(json.dumps({"tasks": {"workbuddy-intl": {
                "label": "WorkBuddy 国际版", "platform": "workbuddy", "account": "expected"}}}))
            row = {"platform": "workbuddy", "account": "another", "business_date": "2026-10-21",
                   "execution_status": "ok", "reason": "activity_sent_reward_unconfirmed", "business": {
                       "activity": "complete", "reward": "unknown", "balance": "complete"}}
            (delivery / "workbuddy-intl.json").write_text(json.dumps(row))
            with patch.object(report, "DELIVERY_ROOT", delivery):
                self.assertEqual(report.build_report("2026-10-21"),
                    "**福利任务异常**\n- WorkBuddy 国际版：结果账号与配置不一致")

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

    def test_telegram_accounts_report_each_unconfirmed_bot_and_stay_silent_when_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            delivery = root / "runtime/delivery"
            delivery.mkdir(parents=True)
            tasks = {"telegram-ai": {"label": "Telegram tg-ai", "platform": "telegram", "account": "tg-ai"},
                     "telegram-nsfw": {"label": "Telegram tg-nsfw", "platform": "telegram", "account": "tg-nsfw"}}
            (root / "benefits-deployment.json").write_text(json.dumps({"tasks": tasks}))
            def write(key, **row):
                base = {"platform": "telegram", "account": tasks[key]["account"], "business_date": "2026-10-19",
                        "execution_status": "ok", "reason": "all_bots_confirmed", "business": {"checkin": "complete"},
                        "details": {"metrics": {}, "items": []}}
                (delivery / (key + ".json")).write_text(json.dumps({**base, **row}))
            write("telegram-ai")
            write("telegram-nsfw")
            with patch.object(report, "DELIVERY_ROOT", delivery):
                self.assertEqual(report.build_report("2026-10-19"), "")
                write("telegram-nsfw", reason="bots_incomplete", business={"checkin": "incomplete"},
                      details={"metrics": {}, "items": [
                          {"id": "a", "name": "@xhgsgk_bot", "status": "incomplete", "reason": "bot_rejected"},
                          {"id": "b", "name": "@okbot", "status": "complete", "reason": "checkin_confirmed"},
                          {"id": "c", "name": "@offbot", "status": "not_applicable", "reason": "bot_disabled"},
                          {"id": "d", "name": "@slowbot", "status": "unknown", "reason": "reply_timeout"}]})
                write("telegram-ai", execution_status="failed", reason="telegram_app_unavailable",
                      business={"checkin": "unknown"})
                text = report.build_report("2026-10-19")
            self.assertIn("- Telegram tg-ai：无法打开 Telegram 网页", text)
            self.assertIn("- Telegram tg-nsfw：@xhgsgk_bot被拒绝（验证题或入群门槛），需手动签到、@slowbot未回复", text)
            self.assertNotIn("@okbot", text)
            self.assertNotIn("@offbot", text)
            self.assertNotIn("签到未完成", text)

    def test_telegram_jobs_are_installed_scheduled_and_summarised(self):
        manifest = json.loads((ROOT / "hermes/manifest.json").read_text())["profile_scripts"]
        schedules = {row["name"]: row for row in json.loads((ROOT / "hermes/schedules.json").read_text())}
        for key, name in (("telegram-ai", "benefits_telegram_ai.py"), ("telegram-nsfw", "benefits_telegram_nsfw.py")):
            self.assertEqual(manifest[name], "hermes/" + name)
            self.assertIn("main('" + key + "')", (ROOT / "hermes" / name).read_text())
            job = schedules["benefits-" + key]
            self.assertEqual(job["source"], "hermes/" + name)
            self.assertTrue(job["no_agent"])
            minute, hour = job["schedule"]["expr"].split()[:2]
            self.assertGreaterEqual(int(hour), 1)
        text = summary.describe("telegram", {"execution_status": "ok", "business": {"checkin": "incomplete"},
            "details": {"metrics": {"bots": {"unit": "count", "current": 6, "max": 7},
                                     "points_qingbaoju": {"unit": "points", "current": 6}},
                        "items": [{"name": "@xhgsgk_bot", "status": "incomplete", "reason": "bot_rejected"}]}})
        self.assertIn("机器人 6/7", text)
        self.assertIn("@xhgsgk_bot bot_rejected", text)
        self.assertIn("qingbaoju 6", text)


if __name__ == "__main__":
    unittest.main()
