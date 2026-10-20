"""把周报中用户明确填写的阶段进度写回目标评论。"""

from __future__ import annotations

from datetime import datetime
import json
import re

from review.stages import StageService
from review.state import StateRepository


class StageWritebackProjection:
    """只识别带稳定目标 ID 的阶段进度行。"""

    PATTERN = re.compile(r"^阶段进度：\[([^]]+)]\s*(.+)$")

    def __init__(self, state: StateRepository, service: StageService) -> None:
        """绑定状态库和阶段账本服务。"""

        self.state = state
        self.service = service

    def apply(self, content: str, dry_run: bool = False) -> list[dict]:
        """逐条评论并更新投影索引；没有显式目标 ID 时不推断。"""

        updates: list[dict] = []
        for raw in content.splitlines():
            match = self.PATTERN.match(raw.strip())
            if not match:
                continue
            goal_id, note = match.group(1).strip(), match.group(2).strip()
            if goal_id == "目标ID":
                continue
            result = self.service.comment_goal(goal_id, note, dry_run)
            updates.append({"goal_id": goal_id, "note": note, "result": result})
            if dry_run:
                continue
            with self.state.connect() as connection:
                row = connection.execute("SELECT payload_json FROM stage_goals WHERE id=?", (goal_id,)).fetchone()
                if not row:
                    raise ValueError(f"阶段目标不存在：{goal_id}")
                payload = json.loads(row["payload_json"])
                payload["progress"] = note
                payload["updated_from_weekly"] = datetime.now().astimezone().isoformat()
                connection.execute(
                    "UPDATE stage_goals SET payload_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), goal_id),
                )
        return updates
