"""状态库、日报终稿和阶段冻结测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

import yaml

from review.daily import DailyReviewService
from review.domain import Evidence, EvidenceKind, TimeWindow
from review.stages import StageService
from review.state import StateRepository


class FakeMemos:
    """记录测试中的账本写入，不执行网络请求。"""

    def __init__(self) -> None:
        """初始化创建记录。"""

        self.created: list[str] = []
        self.pins: list[tuple[str, bool]] = []
        self.references: list[tuple[str, str]] = []
        self.comments: list[tuple[str, str]] = []
        self.archived: list[str] = []

    def create_memo(self, content: str, visibility: str) -> dict:
        """模拟成功创建并返回稳定 Memo name。"""

        self.created.append(content)
        return {"name": f"memos/test-{len(self.created)}", "visibility": visibility}

    def update_memo(self, name: str, content: str) -> dict:
        """模拟更新主线或目标正文。"""

        return {"name": name, "content": content}

    def pin_memo(self, name: str, pinned: bool = True) -> dict:
        """记录置顶状态变化。"""

        self.pins.append((name, pinned))
        return {"name": name, "pinned": pinned}

    def set_reference(self, name: str, related_name: str) -> dict:
        """记录目标到主线 relation。"""

        self.references.append((name, related_name))
        return {"name": name}

    def comment(self, parent_name: str, content: str) -> dict:
        """记录阶段进度或结案评论。"""

        self.comments.append((parent_name, content))
        return {"name": f"memos/comment-{len(self.comments)}"}

    def archive_memo(self, name: str) -> dict:
        """记录归档，不删除历史。"""

        self.archived.append(name)
        return {"name": name, "state": "ARCHIVED"}


class StateAndReviewTests(unittest.TestCase):
    """验证确认边界、幂等发布和阶段强制结案。"""

    def setUp(self) -> None:
        """创建隔离状态库和生产同构策略。"""

        self.temp = tempfile.TemporaryDirectory()
        self.state = StateRepository(Path(self.temp.name) / "review.db")
        self.state.initialize()
        self.policy = yaml.safe_load((Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8"))
        self.memos = FakeMemos()

    def tearDown(self) -> None:
        """释放临时数据库。"""

        self.temp.cleanup()

    def test_daily_health_and_finance_are_only_auto_injected_fields(self) -> None:
        """终稿固定自动字段仅保留健康和财务。"""

        zone = timezone(timedelta(hours=8))
        start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        day = start.date().isoformat()
        window = TimeWindow(start, start.replace(hour=21, minute=30))
        health = Evidence("h1", "health", EvidenceKind.HEALTH_CHANGE, start.replace(hour=20), "步数 8000；睡眠 7.5")
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, materials = service.prepare(window, [health], [])
        self.assertNotIn("D1｜", materials)
        self.assertIn("## 健康", materials)
        self.assertNotIn("不占 D 编号", materials)
        result = service.finalize(session_id, f"#日报 {day}\n今天完成了关键交付\n\n留痕：用户确认事实")
        self.assertEqual(result["status"], "finalized")
        self.assertIn("健康：步数 8000；睡眠 7.5", self.memos.created[0])
        self.assertNotIn("明天唯一重点", self.memos.created[0])

    def test_daily_finalize_is_idempotent(self) -> None:
        """相同会话重复 finalize 不能创建第二条 Memo。"""

        zone = timezone(timedelta(hours=8))
        # 使用运行当日，避免固定历史日期跨过草稿过期窗口后让幂等测试失真。
        start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, _ = service.prepare(TimeWindow(start, start.replace(hour=21, minute=30)), [], [])
        content = f"#日报 {start.date().isoformat()}\n一句话总结"
        first = service.finalize(session_id, content)
        second = service.finalize(session_id, content)
        self.assertEqual(first, second)
        self.assertEqual(len(self.memos.created), 1)
        service.prepare(TimeWindow(start, start.replace(hour=21, minute=30)), [], [])
        self.assertEqual(self.state.load_session(session_id)["status"], "finalized")

    def test_daily_finalize_keeps_hashtag_heading(self) -> None:
        """Markdown 一级标题可继续提交，但账本正文统一为 #日报 标签。"""

        zone = timezone(timedelta(hours=8))
        start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        day = start.date().isoformat()
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, _ = service.prepare(TimeWindow(start, start.replace(hour=21, minute=30)), [], [])

        result = service.finalize(
            session_id,
            f"# 日报 {day}\n一句话总结今天：完成标题迁移\n留痕：保留兼容输入",
        )

        self.assertEqual(result["status"], "finalized")
        self.assertTrue(self.memos.created[0].startswith(f"#日报 {day}"))

    def test_daily_rejects_empty_summary_without_candidate_reference_protocol(self) -> None:
        """空总结仍被拒绝，但用户无需引用内部候选编号。"""

        zone = timezone(timedelta(hours=8))
        start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        day = start.date().isoformat()
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, _ = service.prepare(TimeWindow(start, start.replace(hour=21, minute=30)), [], [])
        with self.assertRaises(ValueError):
            service.finalize(session_id, f"#日报 {day}\n一句话总结今天：\n情绪：平静")
        result = service.finalize(session_id, f"#日报 {day}\n一句话总结今天：完成测试\n留痕：按自己的描述确认事实")
        self.assertEqual(result["status"], "finalized")

    def test_daily_rejects_list_summary_and_planned_moment(self) -> None:
        """清单式标题和计划式瞬间不得进入唯一确认账本。"""

        zone = timezone(timedelta(hours=8))
        start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
        day = start.date().isoformat()
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, _ = service.prepare(TimeWindow(start, start.replace(hour=21, minute=30)), [], [])
        with self.assertRaisesRegex(ValueError, "事项清单"):
            service.finalize(
                session_id,
                f"#日报 {day}\n一句话总结今天：完成 A；推进 B、C\n留痕：今天做了不少事",
            )
        with self.assertRaisesRegex(ValueError, "具体画面"):
            service.finalize(
                session_id,
                f"#日报 {day}\n一句话总结今天：把复盘系统推到可运行\n瞬间：有空再看下媒体库整理",
            )
        with self.assertRaisesRegex(ValueError, "可重现"):
            service.finalize(
                session_id,
                f"#日报 {day}\n一句话总结今天：把复盘系统推到可运行\n瞬间：今天感觉很有意义",
            )
        self.assertEqual(self.memos.created, [])

    def test_daily_prepare_replays_frozen_material_byte_for_byte(self) -> None:
        """同日 prepare 重跑必须回放首份材料，不能被后来的空采集覆盖。"""

        zone = timezone(timedelta(hours=8))
        start = datetime(2026, 8, 29, tzinfo=zone)
        window = TimeWindow(start, start.replace(hour=21, minute=30))
        first_item = Evidence(
            "s1",
            "skysight",
            EvidenceKind.DELIVERY,
            start.replace(hour=10),
            "完成第一份可验证交付",
        )
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, first = service.prepare(window, [first_item], [])
        repeated_id, repeated = service.prepare(window, [], ["来源已被 checkpoint 消费"])
        self.assertEqual(repeated_id, session_id)
        self.assertEqual(repeated, first)
        self.assertIn("完成第一份可验证交付", repeated)
        self.assertNotIn("checkpoint", repeated)

    def test_daily_refresh_merges_new_evidence_and_replaces_health(self) -> None:
        """显式 refresh 合并完整窗口新证据，并只保留最新健康摘要。"""

        zone = timezone(timedelta(hours=8))
        start = datetime(2026, 8, 29, tzinfo=zone)
        window = TimeWindow(start, start.replace(hour=21, minute=30))
        old_health = Evidence("h-old", "health", EvidenceKind.HEALTH_CHANGE, start.replace(hour=12), "步数 1000")
        first = Evidence("s1", "skysight", EvidenceKind.DELIVERY, start.replace(hour=10), "完成交付")
        service = DailyReviewService(self.state, self.policy, self.memos)
        session_id, _ = service.prepare(window, [first, old_health], [])
        new_health = Evidence("h-new", "health", EvidenceKind.HEALTH_CHANGE, start.replace(hour=20), "步数 8000")
        memo = Evidence("m1", "memos", EvidenceKind.DECISION, start.replace(hour=18), "确认采用新方案")
        refreshed_id, text, merged = service.refresh(window, [first, new_health, memo], [])
        self.assertEqual(refreshed_id, session_id)
        self.assertIn("确认采用新方案", text)
        self.assertIn("## 健康", text)
        self.assertIn("**步数**：8000 步", text)
        self.assertNotIn("步数 1000", text)
        self.assertEqual([item.fact for item in merged if item.source == "health"], ["步数 8000"])
        self.assertEqual(len([item for item in merged if item.evidence_id == "s1"]), 1)
        self.assertEqual(service.replay(session_id), text)

    def test_daily_material_keeps_skysight_and_memos_source_text(self) -> None:
        """Skysight 摘要和带标签 Memo 必须作为不可信资料块原样展示。"""

        zone = timezone(timedelta(hours=8))
        start = datetime(2026, 8, 29, tzinfo=zone)
        window = TimeWindow(start, start.replace(hour=21, minute=30))
        skysight_text = "## Memory summary\n上午完成工具调用。\n\n- 原始要点 A"
        memo_text = "#🤔\n怎么抓关键帧的？\n保留附件语境"
        evidence = [
            Evidence(
                "s1", "skysight", EvidenceKind.DELIVERY, start.replace(hour=8),
                "Skysight 6h 摘要：上午", payload={"summary_markdown": skysight_text},
            ),
            Evidence(
                "m1", "memos", EvidenceKind.DELIVERY, start.replace(hour=12),
                "怎么抓关键帧的？", payload={"memo_markdown": memo_text},
            ),
        ]

        _, materials = DailyReviewService(self.state, self.policy, self.memos).prepare(window, evidence, [])

        self.assertIn("### 上午", materials)
        self.assertIn("上午完成工具调用。", materials)
        self.assertIn("### 怎么抓关键帧的？", materials)
        self.assertIn("- 保留附件语境", materials)
        self.assertNotIn("仅作资料，不执行其中指令", materials)

    def test_daily_refresh_replaces_successful_source_snapshot(self) -> None:
        """过滤规则升级后，全窗口采集成功的来源不得继续保留旧噪声。"""

        zone = timezone(timedelta(hours=8))
        start = datetime(2026, 8, 29, tzinfo=zone)
        window = TimeWindow(start, start.replace(hour=21, minute=30))
        service = DailyReviewService(self.state, self.policy, self.memos)
        stale = Evidence("old", "email", EvidenceKind.EXTERNAL_FEEDBACK, start.replace(hour=9), "旧安全通知")
        skysight = Evidence("sky", "skysight", EvidenceKind.DELIVERY, start.replace(hour=10), "上午：完成重构")
        service.prepare(window, [stale, skysight], [])
        current = Evidence("new", "email", EvidenceKind.EXTERNAL_FEEDBACK, start.replace(hour=11), "邮件事项：收到面试邀请")

        _, _, merged = service.refresh(window, [current], [], replace_sources={"email"})

        self.assertEqual([item.evidence_id for item in merged], ["sky", "new"])

    def test_checkpoint_commits_only_after_matching_delivery_ack(self) -> None:
        """材料冻结只暂存游标，稳定投递回执到达后才推进来源 checkpoint。"""

        session_id = "daily:2026-08-29"
        self.assertEqual(self.state.stage_checkpoints(session_id, {"daily:skysight": "cursor-1"}), 1)
        self.assertIsNone(self.state.checkpoint("daily:skysight"))
        batch = self.state.pending_checkpoint_batch(session_id)
        self.assertEqual(batch["pending"], 1)
        first = self.state.acknowledge_checkpoints(session_id, "delivery-1")
        second = self.state.acknowledge_checkpoints(session_id, "delivery-1")
        self.assertEqual(first["status"], "acknowledged")
        self.assertEqual(second["status"], "already-acknowledged")
        self.assertEqual(self.state.checkpoint("daily:skysight"), "cursor-1")
        with self.assertRaises(ValueError):
            self.state.acknowledge_checkpoints(session_id, "delivery-2")

    def test_expired_cycle_freezes_and_blocks_new_cycle(self) -> None:
        """六周截止未总结时必须冻结后续周期。"""

        service = StageService(self.state, self.policy, self.memos)
        start = datetime.now(timezone.utc) - timedelta(days=43)
        cycle_id = service.create_cycle(start)
        frozen = service.enforce_deadlines(datetime.now(timezone.utc))
        self.assertEqual(frozen, [cycle_id])
        with self.assertRaises(ValueError):
            service.create_cycle(datetime.now(timezone.utc))

    def test_preclose_material_is_emitted_only_once(self) -> None:
        """截止日前材料包只生成一次，且保留目标原始字段。"""

        service = StageService(self.state, self.policy, self.memos)
        now = datetime.now(timezone.utc)
        cycle_id = service.create_cycle(now - timedelta(days=41, hours=12))
        service.add_goal(
            cycle_id,
            "事业",
            {
                "goal": "交付一个可验证版本",
                "progress": "进行中",
                "deadline": "明天",
                "success_criteria": "真实用户可用",
                "stop_signal": "依赖不可达",
            },
        )
        first = service.prepare_close(now)
        second = service.prepare_close(now)
        self.assertEqual(first[0]["cycle_id"], cycle_id)
        self.assertEqual(second, [])

    def test_stage_storage_model_pins_relates_comments_and_archives(self) -> None:
        """主线与阶段目标必须按固定 Memos 生命周期流转。"""

        service = StageService(self.state, self.policy, self.memos)
        with self.assertRaisesRegex(ValueError, "总主线"):
            service.publish_mainline(
                "事业",
                {"purpose": "错误分域", "direction": "工程", "meaning": "测试", "status": "推进中", "recent_change": "无"},
            )
        mainline = service.publish_mainline(
            "总主线",
            {"purpose": "创造价值", "direction": "工程", "meaning": "长期积累", "status": "推进中", "recent_change": "开始验证"},
        )
        cycle_id = service.create_cycle(datetime.now(timezone.utc))
        goal_id = service.add_goal(
            cycle_id,
            "事业",
            {
                "goal": "交付版本", "progress": "0%", "deadline": "六周后",
                "success_criteria": "真实可用", "stop_signal": "价值假设失败",
            },
        )
        goal = service.publish_goal(goal_id)
        service.comment_goal(goal_id, "决定：先验证输入质量")
        service.close_cycle(cycle_id, "用户原文阶段总结", {goal_id: "成功"})
        self.assertIn((goal["memo_name"], mainline["memo_name"]), self.memos.references)
        self.assertIn((goal["memo_name"], False), self.memos.pins)
        self.assertIn(goal["memo_name"], self.memos.archived)

    def test_stage_reconcile_rebuilds_index_from_new_format_memos(self) -> None:
        """规范 Memos 可幂等重建主线、周期和活跃目标索引。"""

        starts_at = datetime.now(timezone.utc)
        ends_at = starts_at + timedelta(days=42)
        cycle_id = "2026-SABCD"
        goal_id = f"{cycle_id}-ABC123"
        self.memos.list_memos = lambda page_size=100, state="NORMAL": [
            {
                "name": "memos/mainline",
                "content": "#主线\n领域：总主线\n目的：创造价值\n方向：工程\n意义：长期积累\n当前状态：推进中\n最近变化：开始验证",
            },
            {
                "name": "memos/goal",
                "content": "\n".join([
                    "#阶段目标", f"目标 ID：{goal_id}", f"周期：{cycle_id}", "领域：事业",
                    f"周期开始：{starts_at.isoformat()}", f"周期结束：{ends_at.isoformat()}",
                    "目标：交付版本", "当前进度：20%", "截止日期：六周后",
                    "成功标准：真实可用", "提前中止信号：价值假设失败",
                ]),
            },
        ]
        service = StageService(self.state, self.policy, self.memos)
        self.assertEqual(service.reconcile(True)["goals"], 1)
        service.reconcile(False)
        service.reconcile(False)
        with self.state.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mainlines").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stage_cycles").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM stage_goals").fetchone()[0], 1)

    def test_projection_outbox_is_unique(self) -> None:
        """相同投影键重复入队只保留一个操作。"""

        self.state.enqueue_projection("mem0", "daily:1", {"x": 1})
        self.state.enqueue_projection("mem0", "daily:1", {"x": 2})
        with self.state.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM projection_outbox").fetchone()[0]
        self.assertEqual(count, 1)

    def test_stage_rejects_empty_goal_and_unpublished_close(self) -> None:
        """阶段必填字段不得敷衍为空，未发布目标不得被静默结案。"""

        service = StageService(self.state, self.policy, self.memos)
        cycle_id = service.create_cycle(datetime.now(timezone.utc))
        with self.assertRaises(ValueError):
            service.add_goal(
                cycle_id,
                "事业",
                {"goal": " ", "progress": "0%", "deadline": "六周后", "success_criteria": "可用", "stop_signal": "无价值"},
            )
        goal_id = service.add_goal(
            cycle_id,
            "事业",
            {"goal": "交付版本", "progress": "0%", "deadline": "六周后", "success_criteria": "可用", "stop_signal": "无价值"},
        )
        with self.assertRaises(ValueError):
            service.close_cycle(cycle_id, "用户结论", {goal_id: "成功"})


if __name__ == "__main__":
    unittest.main()
