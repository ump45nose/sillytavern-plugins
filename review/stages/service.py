"""强制阶段结案边界，禁止静默延期。"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
import uuid

from review.ledger import MemosClient
from review.state import StateRepository


class StageService:
    """管理全局六周周期和最多五个活跃目标。"""

    def __init__(
        self,
        state: StateRepository,
        policy: dict,
        memos: MemosClient | None = None,
        enable_tasks: bool = False,
    ) -> None:
        """注入运行状态、规则和账本。"""

        self.state = state
        self.policy = policy
        self.memos = memos
        self.enable_tasks = enable_tasks

    def create_cycle(self, starts_at: datetime) -> str:
        """在没有活跃或待结案周期时创建新的 42 天周期。"""

        with self.state.connect() as connection:
            blocked = connection.execute(
                "SELECT id,status FROM stage_cycles WHERE status IN ('active','awaiting_close') LIMIT 1"
            ).fetchone()
            if blocked:
                raise ValueError(f"周期 {blocked['id']} 尚未结案")
            cycle_id = f"{starts_at.year}-S{uuid.uuid4().hex[:4].upper()}"
            connection.execute(
                "INSERT INTO stage_cycles(id,starts_at,ends_at,status) VALUES(?,?,?,'active')",
                (cycle_id, starts_at.isoformat(), (starts_at + timedelta(days=42)).isoformat()),
            )
        return cycle_id

    def publish_mainline(self, domain: str | None, payload: dict, dry_run: bool = False) -> dict:
        """创建或更新全局唯一主线 Memo，并保持置顶。"""

        mainline_domain = self.policy["stages"]["mainline_domain"]
        if domain not in {None, mainline_domain}:
            raise ValueError("主线只能使用总主线")
        domain = mainline_domain
        required = {"purpose", "direction", "meaning", "status", "recent_change"}
        if missing := required - set(payload):
            raise ValueError(f"主线缺少字段：{sorted(missing)}")
        self._require_nonempty(payload, required, "主线")
        content = self._mainline_content(domain, payload)
        if dry_run:
            return {"status": "dry-run", "content": content}
        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能发布主线")
        with self.state.connect() as connection:
            existing = connection.execute("SELECT memo_name FROM mainlines WHERE domain=?", (domain,)).fetchone()
        if existing:
            memo_name = str(existing["memo_name"])
            self.memos.update_memo(memo_name, content)
            action = "updated"
        else:
            created = self.memos.create_memo(content, self.policy["memos"]["visibility"])
            memo_name = str(created.get("name") or created.get("memo", {}).get("name") or "")
            if not memo_name.startswith("memos/"):
                raise RuntimeError("Memos 创建成功但未返回规范 memo_name")
            action = "created"
        self.memos.pin_memo(memo_name, True)
        with self.state.connect() as connection:
            connection.execute(
                "INSERT INTO mainlines(domain,memo_name,payload_json,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(domain) DO UPDATE SET memo_name=excluded.memo_name,"
                "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (domain, memo_name, json.dumps(payload, ensure_ascii=False), datetime.now().astimezone().isoformat()),
            )
        return {"status": action, "memo_name": memo_name, "domain": domain}

    def add_goal(self, cycle_id: str, domain: str, payload: dict) -> str:
        """创建目标运行索引；权威正文仍必须由 Memos 保存。"""

        if domain not in self.policy["stages"]["domains"]:
            raise ValueError("未知主线领域")
        required = {"goal", "progress", "deadline", "success_criteria", "stop_signal"}
        if missing := required - set(payload):
            raise ValueError(f"阶段目标缺少字段：{sorted(missing)}")
        self._require_nonempty(payload, required, "阶段目标")
        with self.state.connect() as connection:
            cycle = connection.execute("SELECT status FROM stage_cycles WHERE id=?", (cycle_id,)).fetchone()
            if not cycle or cycle["status"] != "active":
                raise ValueError("阶段周期不存在或已冻结")
            count = connection.execute(
                "SELECT COUNT(*) FROM stage_goals WHERE cycle_id=? AND status='active'", (cycle_id,)
            ).fetchone()[0]
            if count >= int(self.policy["stages"]["max_active_goals"]):
                raise ValueError("活跃阶段目标不能超过五个")
            goal_id = f"{cycle_id}-{uuid.uuid4().hex[:6]}"
            connection.execute(
                "INSERT INTO stage_goals(id,cycle_id,domain,status,payload_json) VALUES(?,?,?,'active',?)",
                (goal_id, cycle_id, domain, json.dumps(payload, ensure_ascii=False)),
            )
        return goal_id

    def publish_goal(self, goal_id: str, dry_run: bool = False) -> dict:
        """把已确认目标发布为置顶 Memo，并关联所属主线。"""

        with self.state.connect() as connection:
            row = connection.execute(
                "SELECT g.id,g.cycle_id,g.domain,g.memo_name,g.payload_json,m.memo_name AS mainline_memo,"
                "c.starts_at,c.ends_at FROM stage_goals g "
                "LEFT JOIN mainlines m ON m.domain=? "
                "JOIN stage_cycles c ON c.id=g.cycle_id WHERE g.id=?",
                (self.policy["stages"]["mainline_domain"], goal_id),
            ).fetchone()
        if not row:
            raise ValueError("阶段目标不存在")
        if not row["mainline_memo"]:
            raise ValueError("必须先发布所属领域主线")
        payload = json.loads(row["payload_json"])
        content = self._goal_content(
            row["id"], row["cycle_id"], row["domain"], row["starts_at"], row["ends_at"], payload
        )
        if dry_run:
            return {"status": "dry-run", "content": content, "mainline_memo": row["mainline_memo"]}
        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能发布阶段目标")
        memo_name = str(row["memo_name"] or "")
        if not memo_name:
            previous = self.state.get_idempotent("stage-goal-publish", goal_id)
            if previous:
                memo_name = str(previous["memo_name"])
            else:
                created = self.memos.create_memo(content, self.policy["memos"]["visibility"])
                memo_name = str(created.get("name") or created.get("memo", {}).get("name") or "")
                if not memo_name.startswith("memos/"):
                    raise RuntimeError("Memos 创建成功但未返回规范 memo_name")
                self.state.put_idempotent("stage-goal-publish", goal_id, {"memo_name": memo_name})
        else:
            self.memos.update_memo(memo_name, content)
        self.memos.pin_memo(memo_name, True)
        self.memos.set_reference(memo_name, str(row["mainline_memo"]))
        with self.state.connect() as connection:
            connection.execute("UPDATE stage_goals SET memo_name=? WHERE id=?", (memo_name, goal_id))
        if self.enable_tasks:
            self.state.enqueue_projection(
                "google_tasks",
                f"stage-goal:{goal_id}",
                {
                    "kind": "stage_goal_parent",
                    "mapping_key": f"stage-goal:{goal_id}",
                    "title": payload["goal"],
                    "goal_id": goal_id,
                    "cycle_id": row["cycle_id"],
                    "memo_name": memo_name,
                    "notes_idempotency_key": f"personal-review:stage-goal:{goal_id}",
                },
            )
        return {"status": "published", "memo_name": memo_name, "goal_id": goal_id}

    def reconcile(self, dry_run: bool = True) -> dict:
        """从固定格式 Memos 校验并重建本地阶段索引，不修改远端账本。"""

        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能核对阶段索引")
        memos = self.memos.list_memos(page_size=100, state="NORMAL")
        mainlines: list[dict] = []
        goals: list[dict] = []
        invalid: list[str] = []
        for memo in memos:
            content = str(memo.get("content") or "").strip()
            name = str(memo.get("name") or "").strip()
            try:
                if re.search(r"(?m)^#主线\s*$", content):
                    mainline = self._parse_mainline(name, content)
                    if mainline["domain"] != self.policy["stages"]["mainline_domain"]:
                        raise ValueError("不是全局主线")
                    mainlines.append(mainline)
                elif re.search(r"(?m)^#阶段目标\s*$", content):
                    goals.append(self._parse_goal(name, content))
            except ValueError:
                invalid.append(name or "unknown")
        result = {
            "status": "dry-run" if dry_run else "reconciled",
            "mainlines": len(mainlines),
            "goals": len(goals),
            "invalid": sorted(invalid),
        }
        if dry_run:
            return result
        if len(mainlines) > 1:
            raise ValueError("Memos 中存在多条总主线，拒绝重建索引")
        now = datetime.now().astimezone().isoformat()
        with self.state.connect() as connection:
            for item in mainlines:
                connection.execute(
                    "INSERT INTO mainlines(domain,memo_name,payload_json,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(domain) DO UPDATE SET memo_name=excluded.memo_name,"
                    "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                    (item["domain"], item["memo_name"], json.dumps(item["payload"], ensure_ascii=False), now),
                )
            for item in goals:
                connection.execute(
                    "INSERT INTO stage_cycles(id,starts_at,ends_at,status) VALUES(?,?,?,'active') "
                    "ON CONFLICT(id) DO UPDATE SET starts_at=excluded.starts_at,ends_at=excluded.ends_at "
                    "WHERE stage_cycles.status='active'",
                    (item["cycle_id"], item["starts_at"], item["ends_at"]),
                )
                connection.execute(
                    "INSERT INTO stage_goals(id,cycle_id,domain,memo_name,status,payload_json) "
                    "VALUES(?,?,?,?, 'active',?) ON CONFLICT(id) DO UPDATE SET "
                    "cycle_id=excluded.cycle_id,domain=excluded.domain,memo_name=excluded.memo_name,"
                    "payload_json=excluded.payload_json WHERE stage_goals.status='active'",
                    (
                        item["goal_id"], item["cycle_id"], item["domain"], item["memo_name"],
                        json.dumps(item["payload"], ensure_ascii=False),
                    ),
                )
        return result

    def comment_goal(self, goal_id: str, user_text: str, dry_run: bool = False) -> dict:
        """把用户确认的阶段进度或决定日志作为目标评论写入。"""

        if not user_text.strip():
            raise ValueError("阶段评论不能为空")
        with self.state.connect() as connection:
            row = connection.execute("SELECT memo_name FROM stage_goals WHERE id=?", (goal_id,)).fetchone()
        if not row or not row["memo_name"]:
            raise ValueError("阶段目标尚未发布到 Memos")
        if dry_run:
            return {"status": "dry-run", "memo_name": row["memo_name"], "content": user_text.strip()}
        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能写入评论")
        key = f"{goal_id}:{uuid.uuid5(uuid.NAMESPACE_URL, user_text.strip()).hex}"
        previous = self.state.get_idempotent("stage-goal-comment", key)
        if previous:
            return previous
        created = self.memos.comment(str(row["memo_name"]), user_text.strip())
        comment_name = str(created.get("name") or created.get("memo", {}).get("name") or "")
        if not comment_name.startswith("memos/"):
            raise RuntimeError("Memos 评论成功但未返回规范 comment_name")
        result = {"status": "commented", "comment_name": comment_name, "goal_id": goal_id}
        self.state.put_idempotent("stage-goal-comment", key, result)
        return result

    def enforce_deadlines(self, now: datetime) -> list[str]:
        """到期未收到用户总结时冻结周期，不替用户判断成功或失败。"""

        frozen: list[str] = []
        with self.state.connect() as connection:
            rows = connection.execute(
                "SELECT id FROM stage_cycles WHERE status='active' AND ends_at<=?", (now.isoformat(),)
            ).fetchall()
            for row in rows:
                connection.execute("UPDATE stage_cycles SET status='awaiting_close' WHERE id=?", (row["id"],))
                connection.execute(
                    "UPDATE stage_goals SET status='awaiting_close' WHERE cycle_id=? AND status='active'", (row["id"],)
                )
                frozen.append(row["id"])
        return frozen

    def prepare_close(self, now: datetime) -> list[dict]:
        """在截止日前一次性冻结原始目标材料，不替用户生成阶段结论。"""

        horizon = now + timedelta(days=int(self.policy["stages"]["preclose_days"]))
        with self.state.connect() as connection:
            cycles = connection.execute(
                "SELECT id,starts_at,ends_at FROM stage_cycles "
                "WHERE status='active' AND ends_at>? AND ends_at<=? ORDER BY ends_at",
                (now.isoformat(), horizon.isoformat()),
            ).fetchall()
        materials: list[dict] = []
        for cycle in cycles:
            cycle_id = str(cycle["id"])
            if self.state.get_idempotent("stage-preclose", cycle_id):
                continue
            with self.state.connect() as connection:
                goals = connection.execute(
                    "SELECT id,domain,payload_json FROM stage_goals WHERE cycle_id=? ORDER BY id",
                    (cycle_id,),
                ).fetchall()
            item = {
                "cycle_id": cycle_id,
                "starts_at": cycle["starts_at"],
                "ends_at": cycle["ends_at"],
                "goals": [
                    {"id": row["id"], "domain": row["domain"], "original": json.loads(row["payload_json"])}
                    for row in goals
                ],
                "template": self.close_template(cycle_id),
            }
            self.state.put_idempotent("stage-preclose", cycle_id, item)
            materials.append(item)
        return materials

    @staticmethod
    def close_template(cycle_id: str) -> str:
        """共享原有结案模板；读取模板不冻结或写入材料。"""
        return (f"#阶段总结 {cycle_id}\n\n"
                "这个 loop 成了没成（成功 / 失败 / 停止）：\n"
                "下个 loop 与判定标准、截止日期、中止信号：\n"
                "这套模板哪个字段我在敷衍，删掉：\n"
                "主线的可观察指标动了吗：")

    def close_cycle(self, cycle_id: str, user_text: str, outcomes: dict[str, str], dry_run: bool = False) -> dict:
        """照抄用户阶段总结并强制每个目标进入终态。"""

        allowed = set(self.policy["stages"]["allowed_terminal_states"])
        if not user_text.strip():
            raise ValueError("阶段总结原文不能为空")
        with self.state.connect() as connection:
            cycle = connection.execute("SELECT status FROM stage_cycles WHERE id=?", (cycle_id,)).fetchone()
            goals = connection.execute("SELECT id,memo_name FROM stage_goals WHERE cycle_id=?", (cycle_id,)).fetchall()
        if not cycle or cycle["status"] not in {"active", "awaiting_close"}:
            raise ValueError("阶段周期不存在或已经结案")
        if not goals:
            raise ValueError("没有阶段目标的周期不能结案")
        if any(not row["memo_name"] for row in goals):
            raise ValueError("所有阶段目标必须先发布到 Memos 才能结案")
        goal_ids = {row["id"] for row in goals}
        if set(outcomes) != goal_ids or not set(outcomes.values()) <= allowed:
            raise ValueError("必须为每个阶段目标给出成功、失败或停止")
        content = f"#阶段总结 {cycle_id}\n\n{user_text.strip()}"
        if dry_run:
            return {"status": "dry-run", "content": content}
        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能结案")
        previous = self.state.get_idempotent("stage-close", cycle_id)
        if previous:
            return previous
        published = self.state.get_idempotent("stage-close-publish", cycle_id)
        if published:
            memo_name = str(published["memo_name"])
        else:
            created = self.memos.create_memo(content, self.policy["memos"]["visibility"])
            memo_name = str(created.get("name") or created.get("memo", {}).get("name") or "")
            if not memo_name.startswith("memos/"):
                raise RuntimeError("Memos 创建成功但未返回规范 memo_name")
            self.state.put_idempotent("stage-close-publish", cycle_id, {"memo_name": memo_name})
        with self.state.connect() as connection:
            goal_rows = connection.execute(
                "SELECT id,memo_name FROM stage_goals WHERE cycle_id=? ORDER BY id", (cycle_id,)
            ).fetchall()
        for goal in goal_rows:
            goal_memo = str(goal["memo_name"] or "")
            if not goal_memo:
                continue
            close_key = f"{cycle_id}:{goal['id']}"
            if not self.state.get_idempotent("stage-goal-close", close_key):
                self.memos.comment(goal_memo, f"结案：{outcomes[goal['id']]}\n阶段总结：{memo_name}")
                self.memos.pin_memo(goal_memo, False)
                self.memos.archive_memo(goal_memo)
                self.state.put_idempotent("stage-goal-close", close_key, {"status": "archived"})
        with self.state.connect() as connection:
            for goal_id, outcome in outcomes.items():
                connection.execute("UPDATE stage_goals SET status=? WHERE id=?", (outcome, goal_id))
            connection.execute(
                "UPDATE stage_cycles SET status='closed',summary_memo=? WHERE id=?", (memo_name, cycle_id)
            )
        result = {"status": "closed", "memo_name": memo_name}
        self.state.put_idempotent("stage-close", cycle_id, result)
        self.state.enqueue_projection("user_md", f"stage-close:{cycle_id}", result)
        self.state.enqueue_projection("mem0", f"stage-close:{cycle_id}", {"content": content, **result})
        return result

    @staticmethod
    def _require_nonempty(payload: dict, fields: set[str], label: str) -> None:
        """拒绝把只含空白的必填字段发布到确认账本。"""

        empty = sorted(field for field in fields if not str(payload.get(field, "")).strip())
        if empty:
            raise ValueError(f"{label}字段不能为空：{empty}")

    @staticmethod
    def _mainline_content(domain: str, payload: dict) -> str:
        """把确认字段渲染为固定主线 Memo 格式。"""

        return "\n".join([
            "#主线", f"领域：{domain}", f"目的：{payload['purpose']}",
            f"方向：{payload['direction']}", f"意义：{payload['meaning']}",
            f"当前状态：{payload['status']}", f"最近变化：{payload['recent_change']}",
        ])

    @staticmethod
    def _goal_content(
        goal_id: str,
        cycle_id: str,
        domain: str,
        starts_at: str,
        ends_at: str,
        payload: dict,
    ) -> str:
        """渲染包含稳定索引字段、可从 Memos 恢复的阶段目标。"""

        return "\n".join([
            "#阶段目标", f"目标 ID：{goal_id}", f"周期：{cycle_id}", f"领域：{domain}",
            f"周期开始：{starts_at}", f"周期结束：{ends_at}",
            f"目标：{payload['goal']}", f"当前进度：{payload['progress']}",
            f"截止日期：{payload['deadline']}", f"成功标准：{payload['success_criteria']}",
            f"提前中止信号：{payload['stop_signal']}",
        ])

    @staticmethod
    def _fields(content: str) -> dict[str, str]:
        """解析 StageService 自己发布的固定“字段：值”正文。"""

        result: dict[str, str] = {}
        for raw in content.splitlines():
            if "：" not in raw:
                continue
            key, value = raw.split("：", 1)
            if key.strip() and value.strip():
                result[key.strip()] = value.strip()
        return result

    @classmethod
    def _parse_mainline(cls, memo_name: str, content: str) -> dict:
        """把规范主线 Memo 解析为本地索引记录。"""

        fields = cls._fields(content)
        mapping = {
            "purpose": "目的", "direction": "方向", "meaning": "意义",
            "status": "当前状态", "recent_change": "最近变化",
        }
        required = {"领域", *mapping.values()}
        if not memo_name.startswith("memos/") or not required.issubset(fields):
            raise ValueError("主线 Memo 缺少稳定字段")
        return {
            "domain": fields["领域"],
            "memo_name": memo_name,
            "payload": {target: fields[source] for target, source in mapping.items()},
        }

    @classmethod
    def _parse_goal(cls, memo_name: str, content: str) -> dict:
        """把新版规范阶段目标 Memo 解析为可恢复索引。"""

        fields = cls._fields(content)
        required = {
            "目标 ID", "周期", "领域", "周期开始", "周期结束", "目标", "当前进度",
            "截止日期", "成功标准", "提前中止信号",
        }
        if not memo_name.startswith("memos/") or not required.issubset(fields):
            raise ValueError("阶段目标 Memo 缺少稳定字段")
        # ISO 时间必须可解析；拒绝从自然语言截止日期推断周期边界。
        datetime.fromisoformat(fields["周期开始"])
        datetime.fromisoformat(fields["周期结束"])
        return {
            "goal_id": fields["目标 ID"], "cycle_id": fields["周期"], "domain": fields["领域"],
            "starts_at": fields["周期开始"], "ends_at": fields["周期结束"], "memo_name": memo_name,
            "payload": {
                "goal": fields["目标"], "progress": fields["当前进度"], "deadline": fields["截止日期"],
                "success_criteria": fields["成功标准"], "stop_signal": fields["提前中止信号"],
            },
        }
