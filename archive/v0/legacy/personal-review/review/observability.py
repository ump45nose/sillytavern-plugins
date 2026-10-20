"""不记录正文或凭据的结构化运行日志。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class StructuredLogger:
    """把运行元数据追加为 JSONL，敏感字段名会被拒绝。"""

    FORBIDDEN_KEYS = {"token", "authorization", "content", "body", "payload", "health_raw", "email_body"}

    def __init__(self, directory: str | Path) -> None:
        """创建受限日志目录，文件按 UTC 日期轮转。"""

        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / f"review-{datetime.now(timezone.utc).date().isoformat()}.jsonl"

    def emit(self, event: str, status: str, **fields: Any) -> None:
        """写入一条无正文事件；遇到敏感字段名立即拒绝。"""

        normalized = {str(key).lower() for key in fields}
        if normalized & self.FORBIDDEN_KEYS:
            raise ValueError("结构化日志包含禁止字段")
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "status": status,
            **fields,
        }
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.path.chmod(0o640)
