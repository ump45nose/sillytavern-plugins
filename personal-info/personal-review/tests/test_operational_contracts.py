"""投影、来源游标和保留策略的运行契约测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest

import yaml

from review.domain import TimeWindow
from review.projections import CurrentStateProjection, ProjectionOutbox
from review.retention import RetentionService
from review.sources import SkysightSummarySource, TaskCompletionSource
from review.state import StateRepository


class OperationalContractTests(unittest.TestCase):
    """验证非权威投影、回流证据和保留动作不会越过账本边界。"""

    def setUp(self) -> None:
        """创建隔离状态库和生产同构策略。"""

        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = StateRepository(self.root / "state.db")
        self.state.initialize()
        self.policy = yaml.safe_load(
            (Path(__file__).parents[1] / "config/review.yaml").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        """释放临时目录。"""

        self.temp.cleanup()

    def test_projection_requires_external_id_and_retries_failed_operation(self) -> None:
        """外部投影不得无回执成功，失败项到退避时间后必须重新可见。"""

        self.state.enqueue_projection("mem0", "daily:1", {"content": "confirmed"})
        outbox = ProjectionOutbox(self.state, self.policy)
        operation = outbox.pending("mem0")[0]
        with self.assertRaises(ValueError):
            outbox.complete(operation["id"], True)
        failed = outbox.complete(operation["id"], False, error="temporary")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(outbox.pending("mem0"), [])
        with self.state.connect() as connection:
            connection.execute(
                "UPDATE projection_outbox SET next_attempt_at=? WHERE id=?",
                ((datetime.now().astimezone() - timedelta(minutes=1)).isoformat(), operation["id"]),
            )
        self.assertEqual(outbox.pending("mem0")[0]["id"], operation["id"])
        completed = outbox.complete(operation["id"], True, external_id="mem0-record-1", receipt={"provider": "mem0", "token": "secret"})
        self.assertEqual(completed["external_id"], "mem0-record-1")
        with self.state.connect() as connection:
            receipt = json.loads(connection.execute(
                "SELECT receipt_json FROM projection_outbox WHERE id=?", (operation["id"],)
            ).fetchone()[0])
        self.assertNotIn("token", receipt)

    def test_task_parent_mapping_and_completion_only_becomes_candidate(self) -> None:
        """Tasks 完成只能回流为候选，且子任务必须引用已同步父任务。"""

        outbox = ProjectionOutbox(self.state, self.policy)
        self.state.enqueue_projection(
            "google_tasks", "stage-goal:g1",
            {"kind": "stage_goal_parent", "mapping_key": "stage-goal:g1", "title": "目标一", "goal_id": "g1"},
        )
        parent = outbox.pending("google_tasks")[0]
        outbox.complete(parent["id"], True, external_id="task-parent")
        self.state.enqueue_projection(
            "google_tasks", "weekly:a1",
            {"kind": "weekly_action_child", "mapping_key": "weekly:a1", "parent_mapping_key": "stage-goal:g1", "title": "行动一"},
        )
        child = outbox.pending("google_tasks")[0]
        outbox.complete(child["id"], True, external_id="task-child")
        occurred = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
        outbox.observe_task("weekly:a1", "task-child", "行动一", "completed", occurred)
        result = TaskCompletionSource(self.state).collect(
            TimeWindow(occurred - timedelta(hours=1), occurred + timedelta(hours=1)), None
        )
        self.assertEqual(len(result.evidence), 1)
        self.assertIn("已标记完成", result.evidence[0].fact)
        with self.state.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM review_sessions").fetchone()[0], 0)

    def test_current_state_projection_contains_only_published_current_records(self) -> None:
        """USER.md 自动区块只显示已发布主线和活跃目标。"""

        now = datetime.now(timezone.utc)
        with self.state.connect() as connection:
            connection.execute(
                "INSERT INTO mainlines(domain,memo_name,payload_json,updated_at) VALUES(?,?,?,?)",
                ("总主线", "memos/main", json.dumps({"status": "验证中", "direction": "交付", "recent_change": "开始试运行"}, ensure_ascii=False), now.isoformat()),
            )
            connection.execute(
                "INSERT INTO stage_cycles(id,starts_at,ends_at,status) VALUES(?,?,?,'active')",
                ("2026-S1", now.isoformat(), (now + timedelta(days=42)).isoformat()),
            )
            connection.execute(
                "INSERT INTO stage_goals(id,cycle_id,domain,memo_name,status,payload_json) VALUES(?,?,?,?,?,?)",
                ("g1", "2026-S1", "事业", "memos/g1", "active", json.dumps({"goal": "交付版本", "progress": "20%", "deadline": "2026-10-01"}, ensure_ascii=False)),
            )
        target = self.root / "USER.md"
        result = CurrentStateProjection(self.state, target).apply()
        self.assertEqual(result["status"], "updated")
        text = target.read_text(encoding="utf-8")
        self.assertIn("交付版本", text)
        self.assertIn("PERSONAL_REVIEW:BEGIN sha256=", text)

    def test_retention_archives_then_expires_quarantine(self) -> None:
        """Raw 到期先压缩到隔离区，超过隔离期后才删除压缩包。"""

        old_raw = self.root / "raw" / "skysight" / "2026-01-01"
        old_raw.mkdir(parents=True)
        (old_raw / "event.json").write_text("{}", encoding="utf-8")
        service = RetentionService(self.state, self.root, self.policy)
        now = datetime(2026, 8, 29, 3, 30, tzinfo=timezone.utc)
        result = service.apply(now)
        self.assertFalse(old_raw.exists())
        archive = Path(result["archived"][0])
        self.assertTrue(archive.is_file())
        expired_time = (now - timedelta(days=8)).timestamp()
        os.utime(archive, (expired_time, expired_time))
        deleted = service.apply(now)
        self.assertEqual(deleted["deleted_archives"], [str(archive)])
        self.assertFalse(archive.exists())

    def test_skysight_summary_is_delivered_verbatim(self) -> None:
        """上游 Memory summary 区块必须逐字透传，不能再由日报代码选句或合并。"""

        directory = self.root / "derived" / "skysight" / "source-summaries"
        directory.mkdir(parents=True)
        path = directory / "2026-08-29T08-00-00-6h-memory-summary.md"
        path.write_text(
            "description: 已完成日报系统重构并锁定账本边界。\n\n"
            "## Memory summary\n"
            "上午直接摘要：完成配置骨架并决定使用 Memos。\n\n"
            "### Relevant prior context\n"
            "这段检索背景不应进入日报。\n\n"
            "### Important non-obvious context about the user\n"
            "这段实体词典也不应进入日报。\n\n"
            "## Recording summary\n"
            "- 已完成配置骨架。\n"
            "- 决定使用 Memos。\n",
            encoding="utf-8",
        )
        start = datetime(2026, 8, 29, tzinfo=timezone.utc)
        result = SkysightSummarySource(self.root).collect(TimeWindow(start, start + timedelta(days=1)), None)
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0].payload["evidence_type"], "source_summary")
        self.assertEqual(result.evidence[0].payload["summary_type"], "6h")
        self.assertEqual(
            result.evidence[0].payload["summary_markdown"],
            "## Memory summary\n上午直接摘要：完成配置骨架并决定使用 Memos。",
        )
        self.assertNotIn("## Recording summary", result.evidence[0].payload["summary_markdown"])
        self.assertNotIn("Relevant prior context", result.evidence[0].payload["summary_markdown"])
        self.assertNotIn("Important non-obvious context", result.evidence[0].payload["summary_markdown"])

    def test_skysight_prefers_upstream_6h_files_without_mixing_10min_files(self) -> None:
        """已有上游 6 小时摘要时只透传该层，避免把 10 分钟子摘要重复附加。"""

        directory = self.root / "derived" / "skysight" / "source-summaries"
        directory.mkdir(parents=True)
        six_hour = directory / "2026-08-29T00-00-00-a-6h-memory-summary.md"
        ten_minute = directory / "2026-08-29T00-10-00-b-memory-summary.md"
        six_hour.write_text("上午六小时摘要", encoding="utf-8")
        ten_minute.write_text("十分钟子摘要", encoding="utf-8")
        start = datetime(2026, 8, 29, tzinfo=timezone.utc)

        result = SkysightSummarySource(self.root).collect(TimeWindow(start, start + timedelta(days=1)), None)

        self.assertEqual([item.source_ref for item in result.evidence], [six_hour.name])
        self.assertEqual(result.evidence[0].payload["summary_markdown"], "上午六小时摘要")


if __name__ == "__main__":
    unittest.main()
