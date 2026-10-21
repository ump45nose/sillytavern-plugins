"""基于已确认日报生成冻结周报材料包。"""

from __future__ import annotations

from datetime import datetime, timedelta
from collections import Counter
import hashlib
import json
import re

from review.domain import Evidence, TimeWindow
from review.ledger import MemosClient
from review.state import StateRepository


class WeeklyReviewService:
    """周报服务；缺失日报只报告覆盖率，禁止自动补造。"""

    def __init__(
        self,
        state: StateRepository,
        policy: dict,
        memos: MemosClient | None = None,
        enable_tasks: bool = False,
    ) -> None:
        """注入状态、策略和可选账本客户端。"""

        self.state = state
        self.policy = policy
        self.memos = memos
        self.enable_tasks = enable_tasks

    def prepare(self, window: TimeWindow, evidence: list[Evidence] | None = None, warnings: list[str] | None = None) -> tuple[str, str]:
        """冻结已确认日报列表并生成空白周报模板。"""

        year, week, _ = window.end.isocalendar()
        label = f"{year}-W{week:02d}"
        session_id = f"weekly:{label}"
        confirmed = self._confirmed_daily(window)
        next_weekly = window.end + timedelta(days=7)
        daily_snapshots = [{"date": row["id"].split(":", 1)[1], "content": row["final_content"]} for row in confirmed]
        auto_evidence = [self._serialize(item) for item in (evidence or [])]
        frozen = {"daily": daily_snapshots, "automatic": auto_evidence, "warnings": warnings or []}
        self.state.save_session(
            {
                "id": session_id,
                "kind": "weekly",
                "window_start": window.start.isoformat(),
                "window_end": window.end.isoformat(),
                "status": "open",
                "evidence_json": json.dumps(frozen, ensure_ascii=False),
                "prepared_at": datetime.now().astimezone().isoformat(),
                "expires_at": next_weekly.isoformat(),
                "final_content": None,
                "memo_name": None,
            }
        )
        summaries = [self._first_summary(item["content"]) for item in daily_snapshots]
        lines = [f"【本周周报材料｜{label}｜覆盖 {len(daily_snapshots)}/7】", "", "本周已确认的七句总结："]
        lines.extend(f"- {text}" for text in summaries if text)
        if not summaries:
            lines.append("- 本周没有已确认日报，系统不会用原始活动补写。")
        emotions = self._emotion_counts(daily_snapshots)
        unresolved = self._repeated_unresolved(daily_snapshots)
        if emotions:
            lines.extend(["", "情绪原词频次：" + "、".join(f"{word}×{count}" for word, count in emotions.items())])
        if unresolved:
            lines.extend(["", "重复未解候选（出现至少三次，仅供你判断）："])
            lines.extend(f"- {name}×{count}" for name, count in unresolved.items())
        health = next((item["fact"] for item in auto_evidence if item.get("source") == "health"), None)
        if health:
            lines.extend(["", f"设备健康周摘要候选：{health}"])
        if warnings:
            lines.extend(["", "来源提示：" + "；".join(sorted(set(warnings)))])
        lines.extend(["", self.blank_template(label)])
        return session_id, "\n".join(lines).strip()

    def finalize(self, session_id: str, user_content: str, dry_run: bool = False) -> dict:
        """发布用户确认周报，并把明确状态更新放入投影 outbox。"""

        session = self.state.load_session(session_id)
        if session is None:
            raise ValueError("周报会话不存在")
        previous = self.state.get_idempotent("weekly-finalize", session_id)
        if previous:
            return previous
        if datetime.now().astimezone() >= datetime.fromisoformat(session["expires_at"]):
            raise ValueError("周报会话已经过期")
        content = user_content.strip()
        label = session_id.split(":", 1)[1]
        if not content.startswith(f"#周报 {label}"):
            raise ValueError("周报首行与冻结周次不一致")
        if not self._has_substantive_content(content):
            raise ValueError("周报至少需要一项用户确认内容")
        self._validate_goal_references(content)
        content = self._inject_health(content, session["evidence_json"])
        if dry_run:
            return {"status": "dry-run", "content": content}
        if self.memos is None:
            raise RuntimeError("未配置 Memos，不能发布终稿")
        created = self.memos.create_memo(content, self.policy["memos"]["visibility"])
        memo_name = str(created.get("name") or created.get("memo", {}).get("name") or "")
        if not memo_name.startswith("memos/"):
            raise RuntimeError("Memos 创建成功但未返回规范 memo_name")
        values = dict(session)
        values.update(status="finalized", final_content=content, memo_name=memo_name)
        self.state.save_session(values)
        result = {"status": "finalized", "memo_name": memo_name}
        self.state.put_idempotent("weekly-finalize", session_id, result)
        payload = {"kind": "weekly", "memo_name": memo_name, "content": content}
        destinations = ["user_md", "mem0", "stage_writeback"]
        for destination in destinations:
            self.state.enqueue_projection(destination, session_id, payload)
        if self.enable_tasks:
            self._enqueue_weekly_actions(session_id, memo_name, content)
        return result

    def _enqueue_weekly_actions(self, session_id: str, memo_name: str, content: str) -> None:
        """把用户用稳定目标 ID 明确选择的周行动投影为子任务。"""

        pattern = re.compile(r"^下周行动：\[([^]]+)]\s*(.+)$")
        for raw in content.splitlines():
            match = pattern.match(raw.strip())
            if not match:
                continue
            goal_id, title = match.group(1).strip(), match.group(2).strip()
            if goal_id == "目标ID":
                continue
            digest = hashlib.sha256(f"{goal_id}\0{title}".encode("utf-8")).hexdigest()[:12]
            self.state.enqueue_projection(
                "google_tasks",
                f"{session_id}:action:{digest}",
                {
                    "kind": "weekly_action_child",
                    "mapping_key": f"weekly-action:{session_id}:{digest}",
                    "parent_mapping_key": f"stage-goal:{goal_id}",
                    "title": title,
                    "goal_id": goal_id,
                    "memo_name": memo_name,
                    "notes_idempotency_key": f"personal-review:{session_id}:action:{digest}",
                },
            )

    def _validate_goal_references(self, content: str) -> None:
        """所有阶段写回和行动都必须引用已发布的当前目标，禁止模糊猜测。"""

        pattern = re.compile(r"^(?:阶段进度|下周行动)：\[([^]]+)]\s*(.+)$")
        references = [
            match.group(1).strip()
            for line in content.splitlines()
            if (match := pattern.match(line.strip())) and match.group(1).strip() != "目标ID"
        ]
        if not references:
            return
        with self.state.connect() as connection:
            rows = connection.execute(
                f"SELECT id FROM stage_goals WHERE id IN ({','.join('?' for _ in references)}) "
                "AND memo_name IS NOT NULL AND status IN ('active','awaiting_close')",
                references,
            ).fetchall()
        valid = {str(row["id"]) for row in rows}
        invalid = sorted(set(references) - valid)
        if invalid:
            raise ValueError(f"周报引用了不存在、未发布或已结案的阶段目标：{invalid}")

    @staticmethod
    def _has_substantive_content(content: str) -> bool:
        """拒绝把整张空模板发布为周报。"""

        placeholders = {line.strip().lstrip('- ').strip()
                        for line in WeeklyReviewService.blank_template('').splitlines()[1:]}
        for line in content.splitlines()[1:]:
            text = line.strip().lstrip("- ").strip()
            if not text or text in placeholders:
                continue
            if "：" in text:
                _, value = text.split("：", 1)
                if value.strip() and value.strip() not in {"（设备数据自动补充）", "继续 / 降级 / 停止", "当前交付｜主要阻碍｜下周投入｜状态", "判断｜理由｜预期｜复盘时间"}:
                    return True
            elif text not in {"状态", "阶段性目标", "下周资源分配", "决定日志"}:
                return True
        return False

    def _confirmed_daily(self, window: TimeWindow) -> list:
        """只读取状态库中已经成功写入 Memos 的日报会话索引。"""

        with self.state.connect() as connection:
            return connection.execute(
                "SELECT * FROM review_sessions WHERE kind='daily' AND status='finalized' "
                "AND window_start>=? AND window_end<=? ORDER BY window_start",
                (window.start.isoformat(), window.end.isoformat()),
            ).fetchall()

    @staticmethod
    def _first_summary(content: str) -> str:
        """取日报标签后的第一条非空文本作为用户确认总结。"""

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return lines[1] if len(lines) > 1 else ""

    @staticmethod
    def _emotion_counts(daily: list[dict]) -> Counter:
        """按用户原词统计情绪，不做近义归一。"""

        values: list[str] = []
        for item in daily:
            for line in item["content"].splitlines():
                if line.strip().startswith("情绪："):
                    value = line.split("：", 1)[1].strip().split(maxsplit=1)[0].strip("+，,；;")
                    if value:
                        values.append(value)
        return Counter(values)

    def _repeated_unresolved(self, daily: list[dict]) -> dict[str, int]:
        """只统计稳定短名字至少出现三次的未解，不贴借口标签。"""

        names: list[str] = []
        for item in daily:
            for line in item["content"].splitlines():
                if line.strip().startswith("未解："):
                    match = re.search(r"\[([^]]+)\]", line)
                    if match:
                        names.append(match.group(1).strip())
        threshold = int(self.policy["weekly"]["repetition_threshold"])
        return {name: count for name, count in Counter(names).items() if count >= threshold}

    @staticmethod
    def _inject_health(content: str, evidence_json: str) -> str:
        """只把冻结的设备健康摘要写入身体字段。"""

        frozen = json.loads(evidence_json)
        health = next((item["fact"] for item in frozen.get("automatic", []) if item.get("source") == "health"), "本周无可用设备数据")
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if line.strip().startswith("- 身体："):
                lines[index] = f"- 身体：{health}"
                return "\n".join(lines).strip()
        lines.append(f"- 身体：{health}")
        return "\n".join(lines).strip()

    @staticmethod
    def _serialize(item: Evidence) -> dict:
        """冻结周报使用的自动证据。"""

        return {
            "evidence_id": item.evidence_id,
            "source": item.source,
            "kind": item.kind.value,
            "occurred_at": item.occurred_at.isoformat(),
            "fact": item.fact,
            "subject": item.subject,
            "source_ref": item.source_ref,
            "payload": item.payload,
        }

    @staticmethod
    def blank_template(label: str) -> str:
        """返回不预填结论的周报模板。"""

        return "\n".join(
            [
                f"#周报 {label}",
                "", "可验证变化：", "重复模式：", "沉淀：", "",
                "状态：", "- 关系：", "- 事业 / 时间 / 钱：", "- 身体：（设备数据自动补充）", "",
                "阶段性目标：", "- 当前交付｜主要阻碍｜下周投入｜状态", "",
                "阶段进度：[目标ID] 当前交付｜主要阻碍｜下周投入｜状态",
                "下周行动：[目标ID] 用户明确选择的行动", "",
                "下周资源分配：", "- 继续 / 降级 / 停止", "",
                "决定日志：", "- 判断｜理由｜预期｜复盘时间",
            ]
        )
