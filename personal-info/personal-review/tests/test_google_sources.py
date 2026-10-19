"""Google Calendar 与 Tasks 最小摘要来源测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
import yaml

from review.domain import TimeWindow
from review.sources.google import GoogleCalendarBriefSource, GoogleTasksBriefSource


class GoogleSourceTests(unittest.TestCase):
    """验证日历和 Tasks 只消费允许的最小字段。"""

    def setUp(self) -> None:
        """创建隔离摘要目录和上海业务窗口。"""

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.zone = timezone(timedelta(hours=8))
        self.start = datetime(2026, 8, 29, tzinfo=self.zone)
        self.window = TimeWindow(self.start, self.start.replace(hour=21, minute=30))
        self.policy = yaml.safe_load(
            (Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        """释放临时目录。"""

        self.temp.cleanup()

    def _write(self, payload: dict) -> None:
        """写入与 no-agent 采集脚本一致的单日摘要。"""

        (self.root / "2026-08-29.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_calendar_keeps_valid_event_and_drops_cancelled_or_outside_window(self) -> None:
        """日历只返回未取消且落在日报窗口内的事件。"""

        self._write(
            {
                "calendar": [
                    {
                        "id": "c1",
                        "summary": "下午做日报重构",
                        "status": "confirmed",
                        "occurred_at": "2026-08-29T14:00:00+08:00",
                        "period": "14:00–15:00",
                        "description": "该字段不应被适配器读取",
                    },
                    {
                        "id": "c2",
                        "summary": "已取消事项",
                        "status": "cancelled",
                        "occurred_at": "2026-08-29T15:00:00+08:00",
                    },
                    {
                        "id": "c3",
                        "summary": "窗口外事项",
                        "status": "confirmed",
                        "occurred_at": "2026-08-29T22:00:00+08:00",
                    },
                ],
                "tasks": [],
                "errors": [],
            }
        )

        result = GoogleCalendarBriefSource(self.root).collect(self.window, None)

        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].fact, "日历：下午做日报重构（14:00–15:00）")
        self.assertNotIn("description", result.evidence[0].payload)

    def test_tasks_keeps_only_completed_items_in_window(self) -> None:
        """Tasks 只把当天完成状态变更作为候选，不展示待办清单。"""

        self._write(
            {
                "calendar": [],
                "tasks": [
                    {
                        "id": "t1",
                        "tasklist_id": "l1",
                        "title": "完成日报来源修复",
                        "status": "completed",
                        "completed_at": "2026-08-29T18:00:00+08:00",
                    },
                    {
                        "id": "t2",
                        "tasklist_id": "l1",
                        "title": "尚未完成的噪声",
                        "status": "needsAction",
                        "completed_at": "2026-08-29T19:00:00+08:00",
                    },
                ],
                "errors": [],
            }
        )

        result = GoogleTasksBriefSource(self.root, self.policy).collect(self.window, None)

        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].fact, "Google Task 已完成：完成日报来源修复")
        self.assertEqual(result.evidence[0].source_ref, "tasks:l1:t1")

    def test_google_source_reports_missing_daily_brief_without_failing_daily(self) -> None:
        """摘要缺失只形成来源提示，不能阻断日报。"""

        result = GoogleCalendarBriefSource(self.root).collect(self.window, None)

        self.assertEqual(result.evidence, [])
        self.assertEqual(result.warnings, ["google_calendar 摘要未就绪"])


if __name__ == "__main__":
    unittest.main()
