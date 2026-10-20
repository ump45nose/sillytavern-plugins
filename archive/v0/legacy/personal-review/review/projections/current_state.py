"""从确认账本索引生成 USER.md 当前状态投影。"""

from __future__ import annotations

import json
from pathlib import Path

from review.projections.user_md import UserMdProjection
from review.state import StateRepository


class CurrentStateProjection:
    """只渲染当前主线、活跃阶段目标和冻结约束。"""

    def __init__(self, state: StateRepository, path: str | Path) -> None:
        """绑定状态索引和 USER.md 路径。"""

        self.state = state
        self.target = UserMdProjection(path)

    def render(self) -> str:
        """从已发布 Memos 的本地索引生成确定性 Markdown。"""

        with self.state.connect() as connection:
            mainlines = connection.execute(
                "SELECT domain,memo_name,payload_json FROM mainlines ORDER BY domain"
            ).fetchall()
            goals = connection.execute(
                "SELECT id,cycle_id,domain,memo_name,status,payload_json FROM stage_goals "
                "WHERE status IN ('active','awaiting_close') AND memo_name IS NOT NULL ORDER BY cycle_id,domain,id"
            ).fetchall()
            frozen = connection.execute(
                "SELECT id,ends_at FROM stage_cycles WHERE status='awaiting_close' ORDER BY ends_at"
            ).fetchall()
        lines = ["## Personal Review 当前状态", "", "### 当前主线"]
        if not mainlines:
            lines.append("- 尚无已确认主线。")
        for row in mainlines:
            payload = json.loads(row["payload_json"])
            lines.append(
                f"- {row['domain']}：{payload['status']}；方向：{payload['direction']}；最近变化：{payload['recent_change']}"
            )
        lines.extend(["", "### 活跃阶段目标"])
        if not goals:
            lines.append("- 尚无已发布的活跃阶段目标。")
        for row in goals:
            payload = json.loads(row["payload_json"])
            lines.append(
                f"- [{row['id']}] {payload['goal']}｜进度：{payload['progress']}｜截止：{payload['deadline']}｜状态：{row['status']}"
            )
        lines.extend(["", "### 关键约束"])
        if frozen:
            for row in frozen:
                lines.append(f"- 周期 {row['id']} 待结案；结案前禁止创建下一周期和行动投影。")
        else:
            lines.append("- 当前无待结案冻结。")
        return "\n".join(lines)

    def apply(self, dry_run: bool = False) -> dict:
        """通过哈希保护区块原子更新 USER.md。"""

        content = self.render()
        updated = self.target.apply(content, dry_run)
        return {"status": "dry-run" if dry_run else "updated", "bytes": len(updated.encode("utf-8")), "content": content if dry_run else None}
