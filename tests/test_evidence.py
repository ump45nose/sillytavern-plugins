"""证据准入和去重测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

import yaml

from review.domain import Evidence, EvidenceKind
from review.evidence import EvidencePipeline


class EvidenceTests(unittest.TestCase):
    """确保日志被排除且确认来源优先。"""

    def setUp(self) -> None:
        """加载生产同构规则。"""

        policy = yaml.safe_load((Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8"))
        self.pipeline = EvidencePipeline(policy)
        self.now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)

    def test_excludes_runtime_logs(self) -> None:
        """Hermes 运行记录不能成为日报候选。"""

        item = Evidence("1", "skysight", EvidenceKind.DELIVERY, self.now, "Hermes 运行 cron 执行成功")
        self.assertEqual(self.pipeline.process([item]), [])

    def test_cross_source_duplicate_prefers_memos(self) -> None:
        """同主体近时间事实应保留人工确认 Memos。"""

        raw = Evidence("1", "skysight", EvidenceKind.DELIVERY, self.now, "完成项目发布", subject="项目A")
        confirmed = Evidence("2", "memos", EvidenceKind.DELIVERY, self.now + timedelta(minutes=2), "项目A 已完成发布", subject="项目A")
        result = self.pipeline.process([raw, confirmed])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].source, "memos")


if __name__ == "__main__":
    unittest.main()

