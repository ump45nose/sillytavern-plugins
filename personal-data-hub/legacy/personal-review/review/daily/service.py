"""构建低负担日报材料包，并只发布用户确认内容。"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Iterable
from zoneinfo import ZoneInfo

from review.daily.material import DailyMaterialBundle, DailyMaterialSection
from review.domain import Evidence, EvidenceKind, TimeWindow
from review.ledger import MemosClient
from review.state import StateRepository


class DailyReviewService:
    """日报业务服务；候选材料和最终账本严格隔离。"""

    def __init__(
        self,
        state: StateRepository,
        policy: dict,
        memos: MemosClient | None = None,
        enable_tasks: bool = False,
        user_memory_path: str | Path | None = None,
    ) -> None:
        """注入运行状态、业务策略及可选 Memos 适配器。"""

        self.state = state
        self.policy = policy
        self.memos = memos
        self.enable_tasks = enable_tasks
        self.user_memory_path = Path(user_memory_path) if user_memory_path else None

    def prepare(self, window: TimeWindow, evidence: Iterable[Evidence], warnings: Iterable[str]) -> tuple[str, str]:
        """首次冻结材料包；同日重跑只回放原材料，不重新采集或改号。"""

        day = window.start.date().isoformat()
        session_id = f"daily:{day}"
        if self.state.load_session(session_id) is not None:
            return session_id, self.replay(session_id)

        items = list(evidence)
        expires = window.end + timedelta(hours=int(self.policy["daily"]["draft_expiry_hours"]))
        serialized = [self._serialize(item) for item in items]
        bundle = self.build_material(window, items, warnings)
        material_text = bundle.to_markdown()
        self.state.save_session(
            {
                "id": session_id,
                "kind": "daily",
                "window_start": window.start.isoformat(),
                "window_end": window.end.isoformat(),
                "status": "open",
                "evidence_json": json.dumps(serialized, ensure_ascii=False),
                "prepared_at": datetime.now().astimezone().isoformat(),
                "expires_at": expires.isoformat(),
                "final_content": None,
                "memo_name": None,
                "material_text": material_text,
                "material_json": json.dumps(bundle.to_dict(include_internal=True), ensure_ascii=False),
            }
        )
        return session_id, material_text

    def replay(self, session_id: str) -> str:
        """逐字回放已冻结材料，保证失败重投不会得到空候选或变化的 D 编号。"""

        session = self.state.load_session(session_id)
        if session is None:
            raise ValueError("日报会话不存在")
        if session["material_text"]:
            return str(session["material_text"])

        # 兼容升级前已存在的会话：只用冻结快照重建，不触碰来源 checkpoint。
        window = TimeWindow(datetime.fromisoformat(session["window_start"]), datetime.fromisoformat(session["window_end"]))
        items = [self._deserialize(item) for item in json.loads(session["evidence_json"])]
        bundle = self.build_material(window, items, [])
        material_text = bundle.to_markdown()
        if session["status"] == "open":
            self.state.refresh_session_material(
                session_id,
                session["evidence_json"],
                material_text,
                json.dumps(bundle.to_dict(include_internal=True), ensure_ascii=False),
                str(session["prepared_at"]),
            )
        return material_text

    def material_snapshot(self, session_id: str) -> dict:
        """从冻结证据重建无内部来源状态的机器可读材料。"""

        session = self.state.load_session(session_id)
        if session is None:
            raise ValueError("日报会话不存在")
        window = TimeWindow(datetime.fromisoformat(session["window_start"]), datetime.fromisoformat(session["window_end"]))
        items = [self._deserialize(item) for item in json.loads(session["evidence_json"])]
        if session["material_json"]:
            payload = json.loads(session["material_json"])
            payload.pop("source_status", None)
            return payload
        return self.build_material(window, items, []).to_dict()

    def refresh(
        self,
        window: TimeWindow,
        evidence: Iterable[Evidence],
        warnings: Iterable[str],
        replace_sources: set[str] | None = None,
    ) -> tuple[str, str, list[Evidence]]:
        """显式刷新完整窗口；成功来源可整源替换，失败来源继续保留旧材料。"""

        day = window.start.date().isoformat()
        session_id = f"daily:{day}"
        current = list(evidence)
        session = self.state.load_session(session_id)
        if session is None:
            session_id, material_text = self.prepare(window, current, warnings)
            return session_id, material_text, current
        if session["status"] != "open":
            raise ValueError("只有 open 日报会话可以 refresh")

        frozen = [self._deserialize(item) for item in json.loads(session["evidence_json"])]
        merged = self._merge_evidence(frozen, current, replace_sources)
        bundle = self.build_material(window, merged, warnings)
        material_text = bundle.to_markdown()
        prepared_at = datetime.now().astimezone().isoformat()
        self.state.refresh_session_material(
            session_id,
            json.dumps([self._serialize(item) for item in merged], ensure_ascii=False),
            material_text,
            json.dumps(bundle.to_dict(include_internal=True), ensure_ascii=False),
            prepared_at,
        )
        return session_id, material_text, merged

    def build_material(
        self,
        window: TimeWindow,
        items: Iterable[Evidence],
        warnings: Iterable[str],
    ) -> DailyMaterialBundle:
        """把冻结证据整理成无编号、无来源元数据的结构化材料。"""

        evidence = list(items)
        sections: list[DailyMaterialSection] = []
        self._append_section(sections, "Skysight", self._skysight_blocks(evidence))
        self._append_section(sections, "Memos", self._memos_blocks(evidence))
        self._append_section(sections, "Google Tasks", self._task_blocks(evidence))
        self._append_section(sections, "日历", self._calendar_blocks(evidence))
        self._append_section(sections, "邮件", self._email_blocks(evidence))
        self._append_section(sections, "健康", self._health_blocks(evidence))
        self._append_section(sections, "财务", self._finance_blocks(evidence))
        self._append_section(sections, "Git", self._git_blocks(evidence))
        self._append_section(sections, "CRM", self._crm_blocks(evidence))
        self._append_section(sections, "当前主线与阶段目标", self._stage_blocks())
        self._append_section(sections, "近期已确认日报", self._recent_review_blocks(window.start.date().isoformat()))
        self._append_section(sections, "长期记忆（仅供判断重要性）", self._stable_memory_blocks())

        previous_focus = self._previous_focus(window.start.date().isoformat())
        if previous_focus:
            self._append_section(
                sections,
                "最近记录的唯一重点",
                (f"- **{previous_focus}**\n- 结合今天的证据判断进展；证据不足就明确说未验证。",),
            )
        warning_list = sorted(set(str(value) for value in warnings if str(value).strip()))
        return DailyMaterialBundle(
            day=window.start.date().isoformat(),
            sections=tuple(sections),
            template=self.blank_template(window.start.date().isoformat()),
            source_status={"warnings": warning_list} if warning_list else {},
        )

    @staticmethod
    def _append_section(
        sections: list[DailyMaterialSection],
        title: str,
        blocks: Iterable[str],
    ) -> None:
        """只追加包含真实内容的展示分区。"""

        values = tuple(value.strip() for value in blocks if value and value.strip())
        if values:
            sections.append(DailyMaterialSection(title, values))

    @staticmethod
    def _strip_memory_heading(value: str) -> str:
        """去掉上游重复的 Memory summary 标题，保留摘要正文。"""

        return re.sub(r"^#{1,6}\s+Memory summary\s*\n", "", value.strip(), count=1, flags=re.IGNORECASE)

    @classmethod
    def _skysight_blocks(cls, items: Iterable[Evidence]) -> tuple[str, ...]:
        """把有覆盖关系的分时记录交给日报模型按时段综合。"""

        periods: dict[str, list[str]] = {}
        for item in sorted((x for x in items if x.source == "skysight"), key=lambda x: x.occurred_at):
            source_text = cls._source_text(item) or item.fact
            period_match = re.search(r"(上午|下午|晚上|凌晨)", item.fact)
            period = period_match.group(1) if period_match else "摘要"
            local_time = item.occurred_at.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
            periods.setdefault(period, []).append(
                f"#### {local_time}\n{cls._strip_memory_heading(source_text)}"
            )
        return tuple(
            f"### {period}\n" + "\n\n".join(entries)
            for period, entries in periods.items()
        )

    @classmethod
    def _memos_blocks(cls, items: Iterable[Evidence]) -> tuple[str, ...]:
        """把带标签 Memo 变成标题和正文，不输出边界说明。"""

        blocks: list[str] = []
        for item in sorted((x for x in items if x.source == "memos"), key=lambda x: x.occurred_at):
            raw = cls._source_text(item) or item.fact
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            lines = [line for line in lines if not re.fullmatch(r"#\S+", line)]
            if not lines:
                continue
            title = lines[0].lstrip("# ")
            body = lines[1:]
            rendered = f"### {title}"
            if body:
                rendered += "\n" + "\n".join(line if line.startswith(("- ", "* ")) else f"- {line}" for line in body)
            blocks.append(rendered)
        return tuple(blocks)

    @staticmethod
    def _task_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """把已完成 Google Tasks 渲染成可扫读列表。"""

        titles: list[str] = []
        for item in items:
            if item.source != "google_tasks":
                continue
            payload_titles = item.payload.get("titles")
            if isinstance(payload_titles, list):
                titles.extend(str(value).strip() for value in payload_titles if str(value).strip())
            elif item.subject and item.subject != "Google Tasks 当日完成":
                titles.append(item.subject.strip())
        titles = list(dict.fromkeys(titles))
        return ("**已完成**\n" + "\n".join(f"- {title}" for title in titles),) if titles else ()

    @staticmethod
    def _calendar_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """展示当日有效日历标题，不暴露事件 ID。"""

        values = [f"- {item.fact.removeprefix('日历：')}" for item in items if item.source == "google_calendar"]
        return ("\n".join(values),) if values else ()

    @staticmethod
    def _email_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """只展示非 GitHub 的已准入邮件事实。"""

        values = [
            f"- {item.fact}" for item in items
            if item.source == "email" and not DailyReviewService._is_github_email(item)
        ]
        return ("\n".join(values),) if values else ()

    @staticmethod
    def _is_github_email(item: Evidence) -> bool:
        """兼容识别新版分类与升级前已冻结的 GitHub 邮件摘要。"""

        if item.payload.get("category") == "github":
            return True
        subject = str(item.subject or "").strip().lower()
        fact = str(item.fact or "").strip().lower()
        source_ref = str(item.source_ref or "").strip().lower()
        return subject == "github 通知摘要" or fact.startswith("github 通知摘要") or source_ref.startswith("github:")

    @staticmethod
    def _health_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """从结构化健康摘要按固定中文标签输出当天已有指标。"""

        health = [item for item in items if item.source == "health"]
        if not health:
            return ()
        summary = max(health, key=lambda item: item.occurred_at).payload
        labels = {
            "steps": ("步数", "步"), "sleep": ("睡眠", "小时"),
            "heart_rate": ("平均心率", "次/分"), "resting_heart_rate": ("静息心率", "次/分"),
            "oxygen_saturation": ("血氧", "%"), "active_calories": ("活动热量", "千卡"),
            "exercise": ("运动", "分钟"),
        }
        values = [
            f"- **{label}**：{summary[key]:g} {unit}"
            for key, (label, unit) in labels.items()
            if isinstance(summary.get(key), (int, float)) and not isinstance(summary.get(key), bool)
        ]
        if not values:
            # 兼容升级前只冻结 fact、没有结构化 payload 的健康证据。
            for part in max(health, key=lambda item: item.occurred_at).fact.split("；"):
                match = re.match(r"\s*([^\d]+?)\s+(.+?)\s*$", part)
                if match:
                    label = match.group(1).strip()
                    value = match.group(2).strip()
                    unit = {"步数": "步", "睡眠": "小时", "平均心率": "次/分", "静息心率": "次/分", "血氧": "%", "活动热量": "千卡", "运动": "分钟"}.get(label, "")
                    values.append(f"- **{label}**：{value}" + (f" {unit}" if unit and unit not in value else ""))
        return ("\n".join(values),) if values else ()

    @staticmethod
    def _finance_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """只展示消费用途、逐项金额和非零收支总计。"""

        finance = [item for item in items if item.source == "finance"]
        if not finance:
            return ()
        payload = max(finance, key=lambda item: item.occurred_at).payload
        rows: list[str] = []
        expense_items = payload.get("expense_items", [])
        if isinstance(expense_items, list):
            for value in expense_items:
                if not isinstance(value, dict):
                    continue
                label = str(value.get("label") or "消费").strip()
                amount = str(value.get("amount") or "").strip()
                currency = str(value.get("currency") or "CNY").strip()
                if amount:
                    rows.append(f"- **{label}**：{DailyReviewService._money(amount, currency)}")
        labels = {"expense": "合计支出", "expense_reimbursement": "垫付支出", "expense_lending": "借出", "expense_repayment": "还款支出",
            "income": "收入", "income_lending": "借入", "income_repayment": "收到还款", "income_reimbursement": "报销收入", "income_refund": "退款", "transfer": "转账"}
        for value in payload.get("totals", []):
            rows.append(f"- **{labels[value['type']]}**：{DailyReviewService._money(value['amount'], value['currency'])}")
        if payload.get("pending_count"):
            rows.append(f"- **待确认**：{payload['pending_count']} 笔")
        return ("\n".join(rows),) if rows else ()

    @staticmethod
    def _money(value: str, currency: str) -> str:
        """用紧凑符号渲染常见币种金额。"""

        symbol = {"CNY": "¥", "USD": "$", "EUR": "€"}.get(currency, f"{currency} ")
        return f"{symbol}{value}"

    @staticmethod
    def _nonzero(value: str) -> bool:
        """安全判断十进制文本是否为非零金额。"""

        try:
            return float(value) != 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _git_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """合并本人提交和与本人工作直接相关的 GitHub 反馈。"""

        git_items = [item for item in items if item.source == "git"]
        rows: list[str] = []
        repositories: set[str] = set()
        login = ""
        if git_items:
            payload = max(git_items, key=lambda item: item.occurred_at).payload
            login = str(payload.get("user") or "").strip().lower()
            for repository in payload.get("repositories", []):
                if not isinstance(repository, dict):
                    continue
                name = str(repository.get("name") or "").strip()
                count = int(repository.get("commit_count") or 0)
                summary = str(repository.get("summary") or "").strip()
                if not name or count <= 0:
                    continue
                repositories.add(name.lower())
                detail = f"{count} 次提交" + (f"，{summary}" if summary else "")
                rows.append(f"- **{name}**：{detail}")
        feedback: list[str] = []
        for item in items:
            if item.source != "email" or not DailyReviewService._is_github_email(item):
                continue
            for subject in item.payload.get("subjects", []):
                text = str(subject).strip()
                match = re.search(r"\[([^]/\s]+/[^]\s]+)]", text)
                repository = match.group(1).lower() if match else ""
                if repository in repositories or (login and repository.startswith(login + "/")):
                    cleaned = DailyReviewService._clean_github_feedback(text)
                    feedback.append(cleaned)
        if feedback:
            rows.append("- **直接反馈**：" + "；".join(list(dict.fromkeys(feedback))[:3]))
        return ("\n".join(rows),) if rows else ()

    @staticmethod
    def _clean_github_feedback(value: str) -> str:
        """保留仓库和反馈重点，移除邮件回复前缀与编号噪声。"""

        text = re.sub(r"^(?:re:\s*)+", "", value.strip(), flags=re.IGNORECASE)
        text = re.sub(r"\s*\((?:PR|Issue)\s*#?[^)]*\)\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*#(?:\[编号已省略]|\d+)\b", "", text)
        return " ".join(text.split())[:180]

    @staticmethod
    def _crm_blocks(items: Iterable[Evidence]) -> tuple[str, ...]:
        """CRM 只有真实变化时才占用日报材料空间。"""

        crm_items = [item for item in items if item.source == "crm"]
        if not crm_items:
            return ()
        item = max(crm_items, key=lambda value: value.occurred_at)
        if int(item.payload.get("change_count", 0)) <= 0:
            return ()
        return (f"- **关系变化**：{item.fact}",)

    def _stage_blocks(self) -> tuple[str, ...]:
        """从现有阶段索引读取已发布的活跃目标，不推断缺失数据。"""

        with self.state.connect() as connection:
            mainlines = connection.execute(
                "SELECT domain,payload_json FROM mainlines WHERE memo_name IS NOT NULL AND domain=?",
                (self.policy["stages"]["mainline_domain"],),
            ).fetchall()
            goals = connection.execute(
                "SELECT g.domain,g.status,g.payload_json FROM stage_goals g "
                "WHERE g.status IN ('active','awaiting_close') AND g.memo_name IS NOT NULL "
                "ORDER BY g.domain,g.id"
            ).fetchall()
        values: list[str] = []
        for row in mainlines:
            payload = json.loads(row["payload_json"])
            status = str(payload.get("status") or "").strip()
            recent = str(payload.get("recent_change") or "").strip()
            details = "；".join(value for value in (status, recent) if value)
            if details:
                values.append(f"- **主线**：{details}")
        for row in goals:
            payload = json.loads(row["payload_json"])
            goal = str(payload.get("goal") or "").strip()
            if not goal:
                continue
            progress = str(payload.get("progress") or "").strip()
            deadline = str(payload.get("deadline") or "").strip()
            details = "；".join(value for value in (progress, f"截止 {deadline}" if deadline else "") if value)
            values.append(f"- **{row['domain']}｜{goal}**" + (f"：{details}" if details else ""))
        return ("\n".join(values),) if values else ()

    @staticmethod
    def _source_text(item: Evidence) -> str | None:
        """返回来源提供的摘要与详细记录，供日报 Agent 综合。"""

        key = "summary_markdown" if item.source == "skysight" else "memo_markdown" if item.source == "memos" else ""
        value = item.payload.get(key) if key else None
        return str(value).strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _health_fact(items: Iterable[Evidence]) -> str:
        """选择冻结材料中最新健康摘要，确保材料展示与终稿注入一致。"""

        health = [item for item in items if item.source == "health"]
        return max(health, key=lambda item: item.occurred_at).fact if health else "本日无可用设备数据"

    @staticmethod
    def _finance_fact(items: Iterable[Evidence]) -> str:
        """选择冻结材料中最新账单汇总。"""

        finance = [item for item in items if item.source == "finance"]
        return max(finance, key=lambda item: item.occurred_at).fact if finance else "本日无可用账单汇总"

    @staticmethod
    def _git_fact(items: Iterable[Evidence]) -> str:
        """选择冻结材料中最新 Git 汇总，禁止展开成多个候选。"""

        git_items = [item for item in items if item.source == "git"]
        return max(git_items, key=lambda item: item.occurred_at).fact if git_items else "本日无可用 Git 汇总"

    @staticmethod
    def _crm_fact(items: Iterable[Evidence]) -> str:
        """选择冻结材料中最新 CRM 汇总，禁止展示关系记录正文。"""

        crm_items = [item for item in items if item.source == "crm"]
        return max(crm_items, key=lambda item: item.occurred_at).fact if crm_items else "本日无可用 CRM 汇总"

    @staticmethod
    def _merge_evidence(
        frozen: list[Evidence],
        current: list[Evidence],
        replace_sources: set[str] | None = None,
    ) -> list[Evidence]:
        """合并快照；完整采集成功的来源先清旧数据，再写入当前版本。"""

        replaced = replace_sources or set()
        automatic_sources = {"health", "finance", "git", "crm"}
        merged: dict[str, Evidence] = {
            item.evidence_id: item
            for item in frozen
            if item.source not in automatic_sources and item.source not in replaced
        }
        for item in current:
            if item.source not in automatic_sources:
                merged[item.evidence_id] = item
        for source in automatic_sources:
            old = [] if source in replaced else [item for item in frozen if item.source == source]
            new = [item for item in current if item.source == source]
            values = [*old, *new]
            if values:
                newest = max(values, key=lambda item: item.occurred_at)
                merged[newest.evidence_id] = newest
        return sorted(merged.values(), key=lambda item: (item.occurred_at, item.source, item.evidence_id))

    def finalize(self, session_id: str, user_content: str, dry_run: bool = False) -> dict:
        """校验并发布用户确认正文；绝不自动拼回候选池。"""

        session = self.state.load_session(session_id)
        if session is None:
            raise ValueError("日报会话不存在")
        if session["status"] == "finalized":
            previous = self.state.get_idempotent("daily-finalize", session_id)
            return previous or {"status": "finalized", "memo_name": session["memo_name"]}
        if datetime.now().astimezone() >= datetime.fromisoformat(session["expires_at"]):
            raise ValueError("日报会话已经过期")
        content = user_content.strip()
        expected_day = session_id.split(":", 1)[1]
        first_line = content.splitlines()[0].strip() if content else ""
        if first_line not in {f"# 日报 {expected_day}", f"#日报 {expected_day}"}:
            raise ValueError("日报日期与冻结窗口不一致")
        if first_line.startswith("# 日报 "):
            # 兼容 Markdown 一级标题输入，但发布前统一成 #日报 标签。
            content = content.replace(first_line, f"#日报 {expected_day}", 1)
        if not self._has_summary(content):
            raise ValueError("日报必须包含一句话总结")
        self._validate_field_quality(content)
        if self._unresolved_count(content) > int(self.policy["daily"]["max_unresolved"]):
            raise ValueError("日报未解项不能超过两项")
        content = self._omit_empty_fields(content)
        content = self._inject_health(content, session["evidence_json"])
        content = self._inject_finance(content, session["evidence_json"])
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
        self.state.put_idempotent("daily-finalize", session_id, result)
        self._enqueue_projections(session_id, memo_name, content)
        return result

    def _enqueue_projections(self, session_id: str, memo_name: str, content: str) -> None:
        """仅把确认后的日报交给下游；投影失败不回滚 Memos。"""

        payload = {"kind": "daily", "memo_name": memo_name, "content": content}
        self.state.enqueue_projection("mem0", session_id, payload)
        self.state.enqueue_projection("user_md", session_id, payload)
        focus = self._field_value(content, "明天唯一重点")
        if self.enable_tasks and focus:
            with self.state.connect() as connection:
                cycle = connection.execute(
                    "SELECT id FROM stage_cycles WHERE status='active' ORDER BY starts_at DESC LIMIT 1"
                ).fetchone()
            self.state.enqueue_projection(
                "google_tasks",
                f"{session_id}:unique-focus",
                {
                    "kind": "daily_unique_focus",
                    "title": focus,
                    "memo_name": memo_name,
                    "cycle_id": cycle["id"] if cycle else None,
                    "notes_idempotency_key": f"personal-review:{session_id}:unique-focus",
                },
            )

    @staticmethod
    def _field_value(content: str, label: str) -> str | None:
        """读取用户明确填写的单行字段，空值不产生投影。"""

        prefix = f"{label}："
        for line in content.splitlines():
            if line.strip().startswith(prefix):
                value = line.split("：", 1)[1].strip()
                return value or None
        return None

    @staticmethod
    def _has_summary(content: str) -> bool:
        """要求一句话总结真实非空，兼容旧版第二行直接写总结。"""

        lines = [line.strip() for line in content.splitlines()]
        for line in lines[1:]:
            if line.startswith("一句话总结今天："):
                return bool(line.split("：", 1)[1].strip())
        field_prefixes = ("情绪：", "健康：", "财务：", "留痕：", "未解：", "明天唯一重点：", "瞬间：")
        return any(line and not line.startswith(field_prefixes) for line in lines[1:])

    def _validate_field_quality(self, content: str) -> None:
        """拒绝清单式标题和计划式“瞬间”，避免合法但失真的终稿入账。"""

        summary = self._field_value(content, "一句话总结今天")
        if summary:
            max_chars = int(self.policy["daily"]["summary_max_chars"])
            if len(summary) > max_chars:
                raise ValueError(f"一句话总结不能超过 {max_chars} 个字符")
            separators = summary.count("；") + summary.count("、")
            if separators > int(self.policy["daily"]["summary_max_list_separators"]):
                raise ValueError("一句话总结不能写成事项清单")

        moment = self._field_value(content, "瞬间")
        if moment:
            forbidden = [str(item) for item in self.policy["daily"]["moment_forbidden_patterns"]]
            matched = [item for item in forbidden if item in moment]
            if matched:
                raise ValueError("瞬间必须是具体画面，不能写计划或待办")
            scene_patterns = [str(item) for item in self.policy["daily"]["moment_scene_patterns"]]
            if len(moment) < int(self.policy["daily"]["moment_min_chars"]) or not any(
                pattern in moment for pattern in scene_patterns
            ):
                raise ValueError("瞬间必须包含可重现的场景、动作或感官细节")

    def _previous_focus(self, current_day: str) -> str | None:
        """最近一份日报未填写重点时，向前找最近一次有记录的重点并标注日期。"""

        with self.state.connect() as connection:
            rows = connection.execute(
                "SELECT id,final_content FROM review_sessions WHERE kind='daily' AND status='finalized' "
                "AND id<? ORDER BY id DESC LIMIT 7",
                (f"daily:{current_day}",),
            ).fetchall()
        for row in rows:
            for line in str(row["final_content"] or "").splitlines():
                if line.strip().startswith("明天唯一重点："):
                    value = line.split("：", 1)[1].strip()
                    if value:
                        return f"{str(row['id']).removeprefix('daily:')}：{value}"
        return None

    def _recent_review_blocks(self, current_day: str) -> tuple[str, ...]:
        """只摘录最近两份已确认日报中的用户原话，提供连续性。"""

        with self.state.connect() as connection:
            rows = connection.execute(
                "SELECT id,final_content FROM review_sessions WHERE kind='daily' AND status='finalized' "
                "AND id<? ORDER BY id DESC LIMIT 2",
                (f"daily:{current_day}",),
            ).fetchall()
        blocks: list[str] = []
        for row in rows:
            selected = [
                line.strip()[:240]
                for line in str(row["final_content"] or "").splitlines()
                if line.strip().startswith(("一句话总结今天：", "留痕：", "未解：", "明天唯一重点："))
                and line.split("：", 1)[-1].strip()
            ]
            if selected:
                blocks.append(f"### {str(row['id']).removeprefix('daily:')}\n" + "\n".join(f"- {line}" for line in selected))
        return tuple(blocks)

    def _stable_memory_blocks(self) -> tuple[str, ...]:
        """只读取长期主线和日记习惯，不能把记忆当作当天事件。"""

        if self.user_memory_path is None or not self.user_memory_path.is_file():
            return ()
        content = self.user_memory_path.read_text(encoding="utf-8")
        blocks: list[str] = []
        for heading in ("长期主线", "日记习惯"):
            match = re.search(rf"(?ms)^## {heading}\s*\n(.*?)(?=^##\s|\Z)", content)
            if not match:
                continue
            lines = [line.strip()[:240] for line in match.group(1).splitlines() if line.strip().startswith("- ")]
            if lines:
                blocks.append(f"### {heading}\n" + "\n".join(lines[:3]))
        return tuple(blocks)

    @staticmethod
    def _unresolved_count(content: str) -> int:
        """统计用户实际填写的未解项；空模板行不计数。"""

        count = 0
        for line in content.splitlines():
            if not line.strip().startswith("未解："):
                continue
            value = line.split("：", 1)[1].strip()
            if value:
                count += max(1, value.count("[") if "[" in value else 1)
        return count

    @staticmethod
    def _omit_empty_fields(content: str) -> str:
        """移除用户未填写的可选字段，降低终稿模板感。"""

        labels = {"情绪", "留痕", "未解", "明天唯一重点", "瞬间"}
        kept: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if "：" in stripped:
                label, value = stripped.split("：", 1)
                if label in labels and not value.strip():
                    continue
            kept.append(line)
        return "\n".join(kept).strip()

    @staticmethod
    def _inject_health(content: str, evidence_json: str) -> str:
        """把冻结窗口的设备摘要写入健康字段，不自动填写其他字段。"""

        evidence = [DailyReviewService._deserialize(item) for item in json.loads(evidence_json)]
        health_items = [item for item in evidence if item.source == "health"]
        health = max(health_items, key=lambda item: item.occurred_at).fact if health_items else ""
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if line.strip().startswith("健康："):
                if health:
                    lines[index] = f"健康：{health}"
                else:
                    lines.pop(index)
                return "\n".join(lines).strip()
        if not health:
            return content.strip()
        insert_at = 2 if len(lines) >= 2 else len(lines)
        lines.insert(insert_at, f"健康：{health}")
        return "\n".join(lines).strip()

    @staticmethod
    def _inject_finance(content: str, evidence_json: str) -> str:
        """把冻结的 NAS 汇总写入财务字段，绝不读取原始 bills JSONL。"""

        evidence = [DailyReviewService._deserialize(item) for item in json.loads(evidence_json)]
        finance_items = [item for item in evidence if item.source == "finance"]
        finance = max(finance_items, key=lambda item: item.occurred_at).fact if finance_items else ""
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if line.strip().startswith("财务："):
                if finance:
                    lines[index] = f"财务：{finance}"
                else:
                    lines.pop(index)
                return "\n".join(lines).strip()
        if not finance:
            return content.strip()
        insert_at = 3 if len(lines) >= 3 else len(lines)
        lines.insert(insert_at, f"财务：{finance}")
        return "\n".join(lines).strip()


    @staticmethod
    def blank_template(day: str) -> str:
        """返回不含自动推断的低负担日报模板。"""

        return "\n".join(
            [
                f"#日报 {day}",
                "一句话总结今天：",
                "",
                "情绪：",
                "健康：",
                "财务：",
                "留痕：",
                "未解：",
                "明天唯一重点：",
                "瞬间：",
            ]
        )

    @staticmethod
    def _serialize(item: Evidence) -> dict:
        """把领域对象转换成不含不可序列化时间的快照。"""

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
    def _deserialize(item: dict) -> Evidence:
        """把冻结 JSON 快照恢复为领域对象，供 replay 与显式 refresh 使用。"""

        return Evidence(
            evidence_id=str(item["evidence_id"]),
            source=str(item["source"]),
            kind=EvidenceKind(str(item["kind"])),
            occurred_at=datetime.fromisoformat(str(item["occurred_at"])),
            fact=str(item["fact"]),
            subject=str(item.get("subject", "")),
            source_ref=str(item.get("source_ref", "")),
            payload=dict(item.get("payload") or {}),
        )
