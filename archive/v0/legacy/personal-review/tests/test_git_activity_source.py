from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from review.daily import DailyReviewService
from review.domain import TimeWindow
from review.sources.git_activity import GitActivitySource, store_git_failure, store_git_mcp_summary, verify_git_summary


ZONE = ZoneInfo("Asia/Shanghai")


class GitActivitySourceTest(unittest.TestCase):
    """验证 Git 汇总始终保持单区块且可注入终稿。"""

    def test_reads_aggregated_daily_summary(self):
        """多个 commit 只产生一个自动证据。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2026-09-03.json").write_text(json.dumps({
                "schema_version": 1,
                "date": "2026-09-03",
                "generated_at": "2026-09-03T21:15:00+08:00",
                "repo_count": 2,
                "commit_count": 3,
                "repositories": [
                    {"name": "alpha", "commit_count": 2, "subjects": ["fix: a", "test: a"]},
                    {"name": "beta", "commit_count": 1, "subjects": ["feat: b"]},
                ],
                "source_sha256": "a" * 64,
            }), encoding="utf-8")
            window = TimeWindow(
                datetime(2026, 9, 3, tzinfo=ZONE),
                datetime(2026, 9, 3, 21, 30, tzinfo=ZONE),
            )
            result = GitActivitySource(root).collect(window, None)
            self.assertFalse(result.warnings)
            self.assertEqual(len(result.evidence), 1)
            self.assertIn("2 个仓库，共 3 次提交", result.evidence[0].fact)
            self.assertIn("alpha 2、beta 1", result.evidence[0].fact)
            self.assertNotIn("fix: a", result.evidence[0].fact)

    def test_imports_minimal_mcp_counts_and_merges_duplicate_repository(self):
        """MCP 结果只落仓库计数，同仓库重复项必须合并。"""

        with tempfile.TemporaryDirectory() as directory:
            result = store_git_mcp_summary(
                directory,
                "2026-09-03",
                {
                    "user": "ump45nose",
                    "repositories": [
                        {"name": "owner/alpha", "commit_count": 1},
                        {"name": "owner/alpha", "commit_count": 2},
                        {"name": "owner/beta", "commit_count": 1},
                    ],
                },
                datetime(2026, 9, 3, 21, 15, tzinfo=ZONE),
            )
            self.assertEqual(result, {"date": "2026-09-03", "repo_count": 2, "commit_count": 4})
            stored = json.loads((Path(directory) / "2026-09-03.json").read_text(encoding="utf-8"))
            self.assertEqual(stored["schema_version"], 2)
            self.assertEqual(stored["repositories"][0]["subjects"], [])

    def test_v2_keeps_limited_subjects_and_verifies_artifact(self):
        """提交主题用于重点摘要，成功必须由当日产物校验确认。"""

        with tempfile.TemporaryDirectory() as directory:
            store_git_mcp_summary(
                directory,
                "2026-09-03",
                {
                    "user": "ump45nose",
                    "repositories": [{
                        "name": "owner/alpha", "commit_count": 2,
                        "subjects": ["feat: 完成材料分区", "fix: 修复 Git 假成功"],
                    }],
                },
                datetime(2026, 9, 3, 21, 15, tzinfo=ZONE),
            )
            verified = verify_git_summary(directory, "2026-09-03")
            stored = json.loads((Path(directory) / "2026-09-03.json").read_text(encoding="utf-8"))

            self.assertEqual(verified["status"], "success")
            self.assertIn("完成材料分区", stored["repositories"][0]["summary"])

    def test_failed_fetch_is_not_zero_commit_summary(self):
        """MCP 失败只写状态，不创建可误读为零提交的汇总。"""

        with tempfile.TemporaryDirectory() as directory:
            store_git_failure(directory, "2026-09-03", datetime(2026, 9, 3, 21, 15, tzinfo=ZONE))
            window = TimeWindow(datetime(2026, 9, 3, tzinfo=ZONE), datetime(2026, 9, 3, 21, 30, tzinfo=ZONE))
            result = GitActivitySource(directory).collect(window, None)

            self.assertEqual(result.evidence, [])
            self.assertEqual(result.warnings, ["Git 来源拉取失败"])
            self.assertFalse((Path(directory) / "2026-09-03.json").exists())

    def test_rejects_unscoped_repository_name(self):
        """拒绝缺少 owner 的仓库名，防止 Agent 写入不可追溯汇总。"""

        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "owner/repo"):
                store_git_mcp_summary(
                    directory,
                    "2026-09-03",
                    {"user": "ump45nose", "repositories": [{"name": "alpha", "commit_count": 1}]},
                    datetime(2026, 9, 3, 21, 15, tzinfo=ZONE),
                )

    def test_zero_commits_differs_from_missing_summary(self):
        """零提交是有效事实，缺文件才产生来源提示。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = {
                "schema_version": 1,
                "date": "2026-09-03",
                "generated_at": "2026-09-03T21:15:00+08:00",
                "repo_count": 0,
                "commit_count": 0,
                "repositories": [],
                "source_sha256": "b" * 64,
            }
            (root / "2026-09-03.json").write_text(json.dumps(payload), encoding="utf-8")
            window = TimeWindow(datetime(2026, 9, 3, tzinfo=ZONE), datetime(2026, 9, 3, 21, 30, tzinfo=ZONE))
            result = GitActivitySource(root).collect(window, None)
            self.assertEqual(result.evidence[0].fact, "今日无已采集 Git 提交")

    def test_final_template_does_not_contain_git_field(self):
        """Git 只作为材料背景，不再成为终稿固定字段。"""

        from review.domain import Evidence, EvidenceKind
        item = Evidence(
            "g1", "git", EvidenceKind.GIT_ACTIVITY,
            datetime(2026, 9, 3, 21, 15, tzinfo=ZONE), "alpha 1 次提交",
        )
        self.assertNotIn("Git：", DailyReviewService.blank_template("2026-09-03"))


if __name__ == "__main__":
    unittest.main()
