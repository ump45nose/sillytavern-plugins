"""邮件和 Memos 来源的强过滤回归测试。"""

from __future__ import annotations

from datetime import datetime, time, timezone
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from review.domain import TimeWindow
from review.sources.email import EmailBriefSource
from review.sources.email_policy import EmailCandidatePolicy
from review.sources.google import GoogleTasksBriefSource
from review.sources.memos import MemosSource


class FakeMemosSourceClient:
    """返回预置 Memo 列表的只读测试客户端。"""

    def __init__(self, memos: list[dict]) -> None:
        """保存测试数据。"""

        self.memos = memos

    def list_memos(self, page_size: int = 100) -> list[dict]:
        """模拟 Memos 列表接口。"""

        return self.memos[:page_size]


class SourceFilterTests(unittest.TestCase):
    """验证敏感邮件和无标签 Memo 无法进入日报。"""

    def setUp(self) -> None:
        """加载生产同构策略。"""

        self.policy = yaml.safe_load(
            (Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8")
        )
        self.start = datetime(2026, 8, 29, tzinfo=timezone.utc)
        self.window = TimeWindow(self.start, datetime.combine(self.start.date(), time(21, 30), timezone.utc))

    def test_email_policy_keeps_only_useful_and_never_security_codes(self) -> None:
        """面试等外部变化可保留，验证码、站内信和普通通知必须丢弃。"""

        policy = EmailCandidatePolicy(self.policy)
        useful = policy.assess("恭喜简历通过，邀请您面试", "Notice@example.com")
        self.assertIsNotNone(useful)
        self.assertNotIn("@", useful.fact)
        self.assertIsNone(policy.assess("52513433 是你的安全码", "security@example.com"))
        self.assertIsNone(policy.assess("[私信]回复：还有工具吗", "noreply@linux.do"))
        self.assertIsNone(policy.assess("普通系统通知", "notification@example.com"))

    def test_email_source_refilters_old_noisy_brief(self) -> None:
        """来源适配器必须兜底过滤旧摘要，不能依赖上游脚本已经升级。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "evidence": [
                    {
                        "fact": "收到邮件：恭喜简历通过，邀请您面试（Notice@example.com）",
                        "subject": "恭喜简历通过，邀请您面试",
                        "occurred_at": "2026-08-29T10:00:00+00:00",
                        "source_ref": "gmail:1",
                    },
                    {
                        "fact": "收到邮件：[私信]回复：还有工具吗（noreply@linux.do）",
                        "subject": "[私信]回复：还有工具吗",
                        "occurred_at": "2026-08-29T11:00:00+00:00",
                        "source_ref": "gmail:2",
                    },
                    {
                        "fact": "收到邮件：52513433 是你的安全码（security@example.com）",
                        "subject": "52513433 是你的安全码",
                        "occurred_at": "2026-08-29T12:00:00+00:00",
                        "source_ref": "gmail:3",
                    },
                ]
            }
            (root / "2026-08-29.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = EmailBriefSource(root, self.policy).collect(self.window, None)
        self.assertEqual(len(result.evidence), 1)
        self.assertIn("邀请您面试", result.evidence[0].fact)
        self.assertNotIn("@", result.evidence[0].fact)

    def test_email_source_compacts_github_notifications_only(self) -> None:
        """GitHub 通知应合为一条，普通高价值邮件仍保持独立候选。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "evidence": [
                    {
                        "fact": "GitHub notification",
                        "subject": "Re: review requested for change A",
                        "sender": "notifications@github.com",
                        "occurred_at": "2026-08-29T10:00:00+00:00",
                        "source_ref": "gmail:github-1",
                    },
                    {
                        "fact": "GitHub notification",
                        "subject": "Re: pull request #2 review requested",
                        "sender": "",
                        "occurred_at": "2026-08-29T10:30:00+00:00",
                        "source_ref": "gmail:github-2",
                    },
                    {
                        "fact": "Interview update",
                        "subject": "邀请您面试",
                        "sender": "hr@example.com",
                        "occurred_at": "2026-08-29T11:00:00+00:00",
                        "source_ref": "gmail:interview",
                    },
                ]
            }
            (root / "2026-08-29.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = EmailBriefSource(root, self.policy).collect(self.window, None)

        self.assertEqual(len(result.evidence), 2)
        github = next(item for item in result.evidence if item.subject == "GitHub 通知摘要")
        self.assertIn("2 条", github.fact)
        self.assertEqual(sum(item.subject == "GitHub 通知摘要" for item in result.evidence), 1)

    def test_google_tasks_source_compacts_completed_items(self) -> None:
        """同日完成的 Google Tasks 应保留标题线索但只占一个候选。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "tasks": [
                    {
                        "id": "task-1",
                        "tasklist_id": "list-1",
                        "title": "整理 Memos",
                        "status": "completed",
                        "completed_at": "2026-08-29T10:00:00+00:00",
                    },
                    {
                        "id": "task-2",
                        "tasklist_id": "list-1",
                        "title": "完成工具验证",
                        "status": "completed",
                        "completed_at": "2026-08-29T11:00:00+00:00",
                    },
                ]
            }
            (root / "2026-08-29.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = GoogleTasksBriefSource(root, self.policy).collect(self.window, None)

        self.assertEqual(len(result.evidence), 1)
        self.assertIn("当天完成 2 项", result.evidence[0].fact)
        self.assertIn("整理 Memos", result.evidence[0].fact)

    def test_memos_source_filters_untagged_and_system_ledger_content(self) -> None:
        """用户标签可准入，但无标签和专用系统账本标签都应被过滤。"""

        memos = [
            {
                "name": "memos/untagged",
                "content": "怎么抓关键帧的？",
                "updateTime": "2026-08-29T10:00:00+00:00",
            },
            {
                "name": "memos/question",
                "content": "#🤔\n怎么抓关键帧的？\n这种抖音视频怎么算？",
                "updateTime": "2026-08-29T11:00:00+00:00",
            },
            {
                "name": "memos/structured",
                "content": "阶段状态变为可验收",
                "tags": [{"name": "阶段目标"}],
                "updateTime": "2026-08-29T12:00:00+00:00",
            },
        ]
        source = MemosSource(
            FakeMemosSourceClient(memos),
            ["日报", "周报", "主线", "阶段目标", "阶段总结", "年度总结"],
        )
        result = source.collect(self.window, None)
        self.assertEqual([item.source_ref for item in result.evidence], ["memos/question"])
        self.assertNotIn("memos/untagged", [item.source_ref for item in result.evidence])
        question = result.evidence[0]
        self.assertEqual(question.payload["tags"], ["🤔"])
        self.assertEqual(question.payload["memo_markdown"], "#🤔\n怎么抓关键帧的？\n这种抖音视频怎么算？")


if __name__ == "__main__":
    unittest.main()
