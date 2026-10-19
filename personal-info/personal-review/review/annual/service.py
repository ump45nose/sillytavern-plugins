"""只汇集确认历史并由用户写年度结论。"""

from __future__ import annotations

from datetime import datetime, timedelta
import json

from review.ledger import MemosClient
from review.state import StateRepository


class AnnualReviewService:
    """构建年度材料包，核心问题固定为主线是否要换。"""

    def __init__(self, state: StateRepository, policy: dict, memos: MemosClient | None = None) -> None:
        """注入运行状态、策略与确认账本。"""

        self.state = state
        self.policy = policy
        self.memos = memos

    def prepare(self, year: int, now: datetime) -> tuple[str, str]:
        """冻结当年已确认周报、阶段结果和决定日志索引，不生成结论。"""

        with self.state.connect() as connection:
            weekly = connection.execute(
                "SELECT id,final_content,memo_name FROM review_sessions "
                "WHERE kind='weekly' AND status='finalized' AND id LIKE ? ORDER BY id",
                (f"weekly:{year}-%",),
            ).fetchall()
            stages = connection.execute(
                "SELECT c.id,c.summary_memo,g.id AS goal_id,g.domain,g.status "
                "FROM stage_cycles c LEFT JOIN stage_goals g ON g.cycle_id=c.id "
                "WHERE c.status='closed' AND c.id LIKE ? ORDER BY c.id,g.id",
                (f"{year}-%",),
            ).fetchall()
            mainlines = connection.execute(
                "SELECT domain,memo_name,payload_json,updated_at FROM mainlines ORDER BY domain"
            ).fetchall()
        materials = {
            "weekly": [
                {"id": row["id"], "memo_name": row["memo_name"], "content": row["final_content"]}
                for row in weekly
            ],
            "stages": [dict(row) for row in stages],
            "mainlines": [
                {"domain": row["domain"], "memo_name": row["memo_name"], "state": json.loads(row["payload_json"]), "updated_at": row["updated_at"]}
                for row in mainlines
            ],
        }
        session_id = f"annual:{year}"
        self.state.save_session(
            {
                "id": session_id,
                "kind": "annual",
                "window_start": f"{year}-01-01T00:00:00{now.strftime('%z')}",
                "window_end": f"{year}-12-31T23:59:59{now.strftime('%z')}",
                "status": "open",
                "evidence_json": json.dumps(materials, ensure_ascii=False),
                "prepared_at": now.isoformat(),
                "expires_at": (now + timedelta(days=60)).isoformat(),
                "final_content": None,
                "memo_name": None,
            }
        )
        lines = [
            f"【年度复盘材料｜{year}】",
            f"已确认周报：{len(weekly)} 份；已结案目标：{len(stages)} 项。",
            f"当前主线快照：{len(mainlines)} 个领域。",
            "请翻阅主线变化、阶段结果和周报中的决定日志，比较预测与实际。",
            "",
            f"#年度总结 {year}",
            "主线要不要换：",
            "预测正确的决定：",
            "预测错误的决定：",
            "共同偏差方向：",
        ]
        return session_id, "\n".join(lines)

    def finalize(self, session_id: str, user_content: str, dry_run: bool = False) -> dict:
        """只发布用户写下的年度结论，绝不自动替换主线。"""

        session = self.state.load_session(session_id)
        if not session or session["kind"] != "annual":
            raise ValueError("年度会话不存在")
        previous = self.state.get_idempotent("annual-finalize", session_id)
        if previous:
            return previous
        if datetime.now().astimezone() >= datetime.fromisoformat(session["expires_at"]):
            raise ValueError("年度会话已经过期")
        year = session_id.split(":", 1)[1]
        content = user_content.strip()
        if not content.startswith(f"#年度总结 {year}"):
            raise ValueError("年度总结首行与年份不一致")
        answer = next(
            (line.split("：", 1)[1].strip() for line in content.splitlines() if line.strip().startswith("主线要不要换：")),
            "",
        )
        if not answer:
            raise ValueError("年度总结必须由用户回答主线要不要换")
        if dry_run:
            return {"status": "dry-run", "content": content}
        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能发布年度总结")
        created = self.memos.create_memo(content, self.policy["memos"]["visibility"])
        memo_name = str(created.get("name") or created.get("memo", {}).get("name") or "")
        if not memo_name.startswith("memos/"):
            raise RuntimeError("Memos 创建成功但未返回规范 memo_name")
        values = dict(session)
        values.update(status="finalized", final_content=content, memo_name=memo_name)
        self.state.save_session(values)
        result = {"status": "finalized", "memo_name": memo_name}
        self.state.put_idempotent("annual-finalize", session_id, result)
        self.state.enqueue_projection("mem0", session_id, {"kind": "annual", "memo_name": memo_name, "content": content})
        return result
