"""年度复盘确认边界测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import yaml

from review.annual import AnnualReviewService
from review.state import StateRepository


class FakeMemos:
    """模拟年度总结发布。"""

    def create_memo(self, content: str, visibility: str) -> dict:
        """返回规范的 Memo name。"""

        return {"name": "memos/annual", "visibility": visibility}


class AnnualReviewTests(unittest.TestCase):
    """验证年度材料不会替用户生成主线结论。"""

    def test_prepare_only_asks_fixed_core_question(self) -> None:
        """无历史时也只询问主线是否更换，不补造结论。"""

        with tempfile.TemporaryDirectory() as directory:
            state = StateRepository(Path(directory) / "state.db")
            state.initialize()
            policy = yaml.safe_load((Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8"))
            session_id, text = AnnualReviewService(state, policy).prepare(2026, datetime.now(timezone.utc))
            self.assertEqual(session_id, "annual:2026")
            self.assertIn("主线要不要换：", text)
            self.assertNotIn("建议更换", text)

    def test_finalize_requires_user_core_answer(self) -> None:
        """年度总结不得由空模板替代用户对唯一核心问题的回答。"""

        with tempfile.TemporaryDirectory() as directory:
            state = StateRepository(Path(directory) / "state.db")
            state.initialize()
            policy = yaml.safe_load((Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8"))
            service = AnnualReviewService(state, policy, FakeMemos())
            session_id, _ = service.prepare(2026, datetime.now(timezone.utc))
            with self.assertRaises(ValueError):
                service.finalize(session_id, "#年度总结 2026\n主线要不要换：")


if __name__ == "__main__":
    unittest.main()
