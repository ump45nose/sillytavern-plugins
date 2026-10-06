"""验证 Personal CRM 每日关系变化只以紧凑自动字段进入日报。"""

from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from review.daily import DailyReviewService
from review.domain import TimeWindow
from review.sources.crm_activity import CrmActivitySource, store_crm_mcp_summary


ZONE = ZoneInfo("Asia/Shanghai")


class CrmActivitySourceTest(unittest.TestCase):
    """覆盖 CRM 汇总落盘、零变化和终稿注入。"""

    def test_import_and_render_does_not_store_private_body(self) -> None:
        """只保存 MCP 聚合字段，正文类未知字段不会进入派生文件。"""

        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "date": "2026-09-06",
                "interactions": {
                    "count": 2,
                    "person_count": 1,
                    "people": ["张三"],
                    "directions": {"mutual": 2},
                    "channels": {"wechat": 2},
                },
                "facts": {"count": 1, "people": ["张三"], "types": {"preference": 1}},
                "reminder_changes": {"count": 1, "people": ["张三"], "statuses": {"completed": 1}},
                "content_summaries": {"张三": ["周末讨论相机和拍照地点"]},
                "unexpected_private_body": "不应落盘",
            }
            result = store_crm_mcp_summary(
                directory,
                "2026-09-06",
                payload,
                datetime(2026, 9, 6, 21, 18, tzinfo=ZONE),
            )
            self.assertEqual(result["interaction_count"], 2)
            stored_text = (Path(directory) / "2026-09-06.json").read_text(encoding="utf-8")
            self.assertNotIn("不应落盘", stored_text)
            source = CrmActivitySource(directory)
            window = TimeWindow(datetime(2026, 9, 6, tzinfo=ZONE), datetime(2026, 9, 6, 21, 30, tzinfo=ZONE))
            evidence = source.collect(window, None).evidence[0]
            self.assertEqual(
                evidence.fact,
                "互动 2 次 / 1 人（张三）；新增事实 1 条；提醒变化 1 项（completed 1）；"
                "内容摘要 张三：周末讨论相机和拍照地点",
            )

    def test_zero_changes_is_distinct_from_missing_file(self) -> None:
        """成功查询的零变化不应被误报为来源不可达。"""

        with tempfile.TemporaryDirectory() as directory:
            store_crm_mcp_summary(
                directory,
                "2026-09-06",
                {
                    "date": "2026-09-06",
                    "interactions": {"count": 0, "people": [], "directions": {}, "channels": {}},
                    "facts": {"count": 0, "people": [], "types": {}},
                    "reminder_changes": {"count": 0, "people": [], "statuses": {}},
                },
                datetime(2026, 9, 6, 21, 18, tzinfo=ZONE),
            )
            window = TimeWindow(datetime(2026, 9, 6, tzinfo=ZONE), datetime(2026, 9, 6, 21, 30, tzinfo=ZONE))
            source = CrmActivitySource(directory)
            result = source.collect(window, None)
            self.assertFalse(result.warnings)
            self.assertEqual(result.evidence[0].fact, "今日 CRM 无关系变化")

            self.assertNotIn("CRM：", DailyReviewService.blank_template("2026-09-06"))


if __name__ == "__main__":
    unittest.main()
