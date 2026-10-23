"""结构化日志脱敏测试。"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from review.observability import StructuredLogger


class StructuredLoggerTests(unittest.TestCase):
    """验证 JSONL 格式与敏感字段拒绝。"""

    def test_emits_json_and_rejects_sensitive_field(self) -> None:
        """运行元数据可记录，但正文和凭据字段不能进入日志。"""

        with tempfile.TemporaryDirectory() as directory:
            logger = StructuredLogger(directory)
            logger.emit("job", "ok", command="daily")
            record = json.loads(logger.path.read_text(encoding="utf-8"))
            self.assertEqual(record["command"], "daily")
            with self.assertRaises(ValueError):
                logger.emit("job", "error", token="secret")


if __name__ == "__main__":
    unittest.main()
