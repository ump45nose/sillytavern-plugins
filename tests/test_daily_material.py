"""日报降噪 Markdown 的黄金回放测试。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

import yaml

from review.daily import DailyReviewService
from review.domain import Evidence, EvidenceKind, TimeWindow
from review.state import StateRepository


ZONE = ZoneInfo("Asia/Shanghai")


class DailyMaterialGoldenTests(unittest.TestCase):
    """使用 2026-09-13 同构证据验证最终材料结构。"""

    def test_2026_09_13_material_is_sectioned_and_noise_free(self) -> None:
        """所有来源必须归入标题，内部证据元数据不得泄露。"""

        with tempfile.TemporaryDirectory() as directory:
            state = StateRepository(Path(directory) / "review.db")
            state.initialize()
            policy = yaml.safe_load((Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8"))
            service = DailyReviewService(state, policy)
            start = datetime(2026, 9, 13, tzinfo=ZONE)
            evidence = [
                Evidence(
                    "secret-sky", "skysight", EvidenceKind.DELIVERY, start.replace(hour=8),
                    "Skysight 上午摘要（上游 6h Memory summary）",
                    payload={"summary_markdown": "## Memory summary\n上午去爬山并寻找拍云点位。"},
                ),
                Evidence(
                    "secret-memo", "memos", EvidenceKind.DELIVERY, start.replace(hour=19),
                    "爬山和拍照有关？",
                    payload={"memo_markdown": "#📷\n爬山和拍照有关？\n拍照能带动走路"},
                ),
                Evidence(
                    "secret-task", "google_tasks", EvidenceKind.DELIVERY, start.replace(hour=16),
                    "Google Task 已完成：摸鱼", subject="摸鱼", payload={"titles": ["摸鱼"]},
                ),
                Evidence(
                    "secret-health", "health", EvidenceKind.HEALTH_CHANGE, start.replace(hour=20),
                    "步数 15426；活动热量 625",
                    payload={"steps": 15426, "active_calories": 625},
                ),
                Evidence(
                    "secret-finance", "finance", EvidenceKind.FINANCE_CHANGE, start.replace(hour=20),
                    "买了：公交 ¥1.99、饮料 ¥3.99；共花 ¥5.98",
                    payload={
                        "expense_items": [
                            {"label": "公交", "amount": "1.99", "currency": "CNY"},
                            {"label": "饮料", "amount": "3.99", "currency": "CNY"},
                        ],
                        "totals": [{"currency": "CNY", "type": "expense", "amount": "5.98", "fee": "0", "count": 2}],
                    },
                ),
                Evidence(
                    "secret-git", "git", EvidenceKind.GIT_ACTIVITY, start.replace(hour=21), "Git summary",
                    payload={
                        "user": "ump45nose",
                        "repositories": [{
                            "name": "ump45nose/zotgo", "commit_count": 3,
                            "summary": "完成发布说明整理", "subjects": ["docs: changelog"],
                        }],
                    },
                ),
                Evidence(
                    "secret-mail", "email", EvidenceKind.EXTERNAL_FEEDBACK, start.replace(hour=19), "GitHub 通知摘要",
                    payload={"category": "github", "subjects": ["Re: [ump45nose/zotgo] PR 已合并"]},
                ),
                Evidence(
                    "secret-crm", "crm", EvidenceKind.RELATIONSHIP, start.replace(hour=21), "今日 CRM 无关系变化",
                    payload={"change_count": 0},
                ),
            ]
            bundle = service.build_material(
                TimeWindow(start, start.replace(hour=21, minute=30)), evidence, ["内部来源失败原因"]
            )
            markdown = bundle.to_markdown()

        self.assertIn("# 今日日报材料｜2026-09-13", markdown)
        self.assertIn("## 日报草稿\n\n#日报 2026-09-13", markdown)
        self.assertIn("## Google Tasks\n\n**已完成**\n- 摸鱼", markdown)
        self.assertIn("## 健康", markdown)
        self.assertIn("- **步数**：15426 步", markdown)
        self.assertIn("## 财务", markdown)
        self.assertIn("- **公交**：¥1.99", markdown)
        self.assertIn("- **合计支出**：¥5.98", markdown)
        self.assertIn("## Git", markdown)
        self.assertIn("**ump45nose/zotgo**：3 次提交，完成发布说明整理", markdown)
        self.assertIn("**直接反馈**", markdown)
        self.assertNotIn("## CRM", markdown)
        for noise in ("D1｜", "secret-", "不占 D 编号", "来源提示", "原文开始", "内部来源失败原因"):
            self.assertNotIn(noise, markdown)
        machine = bundle.to_dict()
        self.assertNotIn("source_status", machine)

    def test_legacy_frozen_github_summary_never_returns_to_email_section(self) -> None:
        """升级前没有 category 的 GitHub 摘要也只能归入 Git 背景。"""

        with tempfile.TemporaryDirectory() as directory:
            state = StateRepository(Path(directory) / "review.db")
            state.initialize()
            policy = yaml.safe_load((Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8"))
            service = DailyReviewService(state, policy)
            start = datetime(2026, 9, 13, tzinfo=ZONE)
            evidence = [
                Evidence(
                    "legacy-github", "email", EvidenceKind.EXTERNAL_FEEDBACK, start.replace(hour=19),
                    "GitHub 通知摘要：15 条", subject="GitHub 通知摘要",
                )
            ]
            markdown = service.build_material(
                TimeWindow(start, start.replace(hour=21, minute=30)), evidence, []
            ).to_markdown()

        self.assertNotIn("## 邮件", markdown)
        self.assertNotIn("GitHub 通知摘要", markdown)


if __name__ == "__main__":
    unittest.main()
