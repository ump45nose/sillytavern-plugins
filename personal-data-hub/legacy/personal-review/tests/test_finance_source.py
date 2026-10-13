from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from review.daily import DailyReviewService
from review.domain import TimeWindow
from review.sources.finance import FinanceSource


ZONE = ZoneInfo("Asia/Shanghai")


class FinanceSourceTest(unittest.TestCase):
    def test_reads_only_summary_and_formats_finance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2026-09-03.json").write_text(json.dumps({
                "schema_version": 1,
                "date": "2026-09-03",
                "generated_at": "2026-09-03T21:20:00+08:00",
                "record_count": 2,
                "state_counts": {"New": 1, "Edited": 0, "Synced": 1},
                "currencies": {"CNY": {
                    "income_money": "100.00", "expense_net_money": "35.00",
                    "expense_gross_money": "40.00", "refund_money": "5.00",
                    "fee": {"total": "-2.00"},
                }},
                "expense_descriptions": {
                    "items": ["午餐", "日用品"],
                    "omitted_count": 1,
                },
                "source_jsonl_sha256": "a" * 64,
            }), encoding="utf-8")
            window = TimeWindow(datetime(2026, 9, 3, tzinfo=ZONE), datetime(2026, 9, 3, 21, 30, tzinfo=ZONE))
            result = FinanceSource(root).collect(window, None)
            self.assertFalse(result.warnings)
            self.assertEqual(len(result.evidence), 1)
            self.assertEqual(result.evidence[0].fact, "共花 ¥35.00；收入 ¥100.00；退款 ¥5.00")

    def test_legacy_summary_without_descriptions_remains_supported(self):
        """历史汇总没有描述字段时仍须正常读取，避免旧日报回放失败。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2026-09-03.json").write_text(json.dumps({
                "schema_version": 1,
                "date": "2026-09-03",
                "generated_at": "2026-09-03T21:20:00+08:00",
                "record_count": 0,
                "state_counts": {},
                "currencies": {},
                "source_jsonl_sha256": "b" * 64,
            }), encoding="utf-8")
            window = TimeWindow(datetime(2026, 9, 3, tzinfo=ZONE), datetime(2026, 9, 3, 21, 30, tzinfo=ZONE))
            result = FinanceSource(root).collect(window, None)
            self.assertFalse(result.warnings)
            self.assertEqual(result.evidence[0].fact, "今天没有支出")

    def test_v2_summary_preserves_item_amounts_for_material(self):
        """新版财务契约必须把用途和逐项金额交给材料渲染器。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2026-09-03.json").write_text(json.dumps({
                "schema_version": 2,
                "date": "2026-09-03",
                "generated_at": "2026-09-03T21:20:00+08:00",
                "record_count": 2,
                "state_counts": {},
                "currencies": {"CNY": {
                    "income_money": "0.00", "expense_net_money": "5.98",
                    "expense_gross_money": "5.98", "refund_money": "0.00", "fee": {"total": "0.00"},
                }},
                "expense_items": [
                    {"label": "公交", "amount": "1.99", "currency": "CNY"},
                    {"label": "饮料", "amount": "3.99", "currency": "CNY"},
                ],
                "source_jsonl_sha256": "c" * 64,
            }), encoding="utf-8")
            window = TimeWindow(datetime(2026, 9, 3, tzinfo=ZONE), datetime(2026, 9, 3, 21, 30, tzinfo=ZONE))
            evidence = FinanceSource(root).collect(window, None).evidence[0]

            self.assertEqual(evidence.fact, "买了：公交 ¥1.99、饮料 ¥3.99；共花 ¥5.98")
            self.assertEqual(evidence.payload["expense_items"][0]["label"], "公交")

    def test_missing_summary_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            window = TimeWindow(datetime(2026, 9, 3, tzinfo=ZONE), datetime(2026, 9, 3, 21, 30, tzinfo=ZONE))
            result = FinanceSource(directory).collect(window, None)
            self.assertEqual(result.evidence, [])
            self.assertEqual(result.warnings, ["本日没有账单汇总"])

    def test_final_injection_uses_frozen_fact(self):
        from review.domain import Evidence, EvidenceKind
        evidence = Evidence("f1", "finance", EvidenceKind.FINANCE_CHANGE,
                            datetime(2026, 9, 3, 21, 20, tzinfo=ZONE), "CNY 收入 1.00，支出 2.00")
        frozen = json.dumps([DailyReviewService._serialize(evidence)], ensure_ascii=False)
        content = "#日报 2026-09-03\n一句话总结今天：测试\n财务：（自动补充）"
        rendered = DailyReviewService._inject_finance(content, frozen)
        self.assertIn("财务：CNY 收入 1.00，支出 2.00", rendered)


if __name__ == "__main__":
    unittest.main()
