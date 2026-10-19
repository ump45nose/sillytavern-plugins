"""Hermes cron 差异和应用测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from review.config import load_config
from review.jobs import CronPlanner


class CronPlannerTests(unittest.TestCase):
    """验证任务比较、dry-run 和 CLI 命令边界。"""

    def setUp(self) -> None:
        """创建隔离 ENV 和 jobs.json。"""

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        template = (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8")
        values: list[str] = []
        for line in template.splitlines():
            if not line.startswith("REVIEW_") or "=" not in line:
                continue
            key = line.split("=", 1)[0]
            if key == "REVIEW_MEMOS_BASE_URL":
                values.append(f"{key}=http://127.0.0.1:5230")
            elif key == "REVIEW_JOBS_FILE":
                values.append(f"{key}={self.root / 'jobs.json'}")
            elif key == "REVIEW_HERMES_BIN":
                values.append(f"{key}=/opt/hermes")
            elif key.startswith("REVIEW_ENABLE_"):
                values.append(line)
            elif key.endswith(("_ROOT", "_FILE", "_DB", "_DIR", "_SPOOL", "_MD")):
                values.append(f"{key}={self.root / key.lower()}")
            else:
                values.append(line)
        self.env = self.root / ".env"
        self.env.write_text("\n".join(values) + "\n", encoding="utf-8")
        self.jobs = self.root / "jobs.json"
        self.jobs.write_text(json.dumps({"jobs": [], "opaque": 1}), encoding="utf-8")
        self.config = load_config(self.env, Path(__file__).parents[1] / "config/review.yaml")

    def tearDown(self) -> None:
        """释放临时目录。"""

        self.temp.cleanup()

    def test_diff_only_creates_managed_jobs(self) -> None:
        """空 jobs 文件应产生完整受管任务计划，且不触碰其他任务。"""

        changes = CronPlanner(self.config).diff()
        self.assertEqual(len(changes), 11)
        self.assertTrue(all(change["action"] == "create" for change in changes))
        email = next(change for change in changes if change["name"] == "personal-review-email-2100")
        self.assertTrue(email["enabled"])
        google = next(change for change in changes if change["name"] == "personal-review-google-2110")
        self.assertTrue(google["enabled"])
        self.assertTrue(google["no_agent"])
        git = next(change for change in changes if change["name"] == "personal-review-git-2115")
        self.assertTrue(git["enabled"])
        self.assertFalse(git["no_agent"])
        self.assertEqual(git["skill"], "personal-review")
        self.assertIn("mcp__github__get_me", git["prompt"])
        self.assertIn("mcp__github__search_commits", git["prompt"])
        self.assertIn("reviewctl git import", git["prompt"])
        self.assertIn("禁止使用 git 命令", git["prompt"])
        attachment = next(change for change in changes if change["name"] == "personal-review-attachments-worker")
        self.assertFalse(attachment["enabled"])
        self.assertNotIn("personal-review-retention", {change["name"] for change in changes})
        ack = next(change for change in changes if change["name"] == "personal-review-daily-ack-2135")
        self.assertFalse(ack["enabled"])
        self.assertTrue(ack["no_agent"])
        daily = next(change for change in changes if change["name"] == "personal-review-daily-2130")
        self.assertIn("## 灵珺的话", daily["prompt"])
        self.assertIn("## 想问你的", daily["prompt"])
        self.assertIn("## 可以怎么走", daily["prompt"])
        self.assertIn("不能补造事实", daily["prompt"])
        self.assertIn("本次仅发送精简回退版", daily["prompt"])
        self.assertIn("Git、CRM 只能在用户认可后写入留痕", daily["prompt"])

    def test_daily_guidance_policy_is_exposed_from_yaml(self) -> None:
        """个性化引导来源和目标必须位于可版本化业务配置中。"""

        guidance = self.config.policy["daily"]["guidance"]
        self.assertEqual(guidance["context_sources"], ["candidate_facts", "user_profile"])
        self.assertIn("stop_condition", guidance["question_targets"])
        self.assertIn("resource_allocation", guidance["action_targets"])
        self.assertEqual(guidance["focus_policy"], "primary_storyline")
        self.assertEqual(guidance["action_option_mode"], "alternative_resource_decisions")
        self.assertEqual(guidance["excluded_action_domains"], ["personal_review_operations"])
        self.assertTrue(guidance["forbid_review_procedure"])
        self.assertTrue(guidance["respect_operational_gates"])

    def test_daily_final_edit_policy_is_explicit_and_skill_bound(self) -> None:
        """轻编辑和图片门槛必须同时存在于配置与用户确认 Skill。"""

        policy = self.config.policy["daily"]["final_edit"]
        self.assertEqual(policy["mode"], "light_compression")
        self.assertEqual(policy["preserve"], ["facts", "first_person_voice", "uncertainty"])
        self.assertEqual(policy["remove"], ["repetition", "filler", "meta_instructions"])
        self.assertTrue(policy["semantic_change_requires_reconfirmation"])
        skill = (Path(__file__).parents[1] / "deploy/skill/personal-review/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("终稿不是聊天记录备份", skill)
        self.assertIn("telegram-image:<缓存文件名>", skill)
        self.assertIn("入队失败时不得静默发布无图终稿", skill)

    def test_dry_run_executes_no_command(self) -> None:
        """apply --dry-run 只能返回计划，不能调用 Hermes。"""

        called: list[list[str]] = []
        result = CronPlanner(self.config).apply(True, lambda command: called.append(list(command)) or "")
        self.assertEqual(result["status"], "dry-run")
        self.assertEqual(called, [])

    def test_duplicate_managed_name_is_rejected(self) -> None:
        """重复受管名称必须阻止 apply，避免覆盖错误任务。"""

        duplicate = {"id": "x", "name": "personal-review-email-2100", "schedule": {"expr": "0 21 * * *"}}
        self.jobs.write_text(json.dumps({"jobs": [duplicate, {**duplicate, "id": "y"}]}), encoding="utf-8")
        with self.assertRaises(ValueError):
            CronPlanner(self.config).diff()


if __name__ == "__main__":
    unittest.main()
