"""健康容错和 USER.md 完整性测试。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from review.domain import TimeWindow
from review.projections import UserMdProjection
from review.sources.health import HealthSource


class HealthAndUserMdTests(unittest.TestCase):
    """覆盖坏快照、重复累计和区块哈希冲突。"""

    def test_health_uses_max_steps_and_ignores_bad_json(self) -> None:
        """累计步数取窗口最大值，坏 JSON 只产生警告。"""

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "health.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE health_payloads(id INTEGER PRIMARY KEY, received_at TEXT, payload_json TEXT)")
            zone = timezone(timedelta(hours=8))
            start = datetime(2026, 8, 29, tzinfo=zone)
            connection.executemany(
                "INSERT INTO health_payloads(received_at,payload_json) VALUES(?,?)",
                [
                    ((start + timedelta(hours=8)).isoformat(), json.dumps({"steps": [{"count": 1000}], "resting_heart_rate": [{"bpm": 60}]})),
                    ((start + timedelta(hours=20)).isoformat(), json.dumps({"steps": [{"count": 8000}], "resting_heart_rate": [{"bpm": 62}]})),
                    ((start + timedelta(hours=21)).isoformat(), "bad-json"),
                ],
            )
            connection.commit()
            connection.close()
            result = HealthSource(database, ["steps", "resting_heart_rate"]).collect(
                TimeWindow(start, start + timedelta(hours=22)), None
            )
            self.assertEqual(result.evidence[0].payload["steps"], 8000)
            self.assertEqual(result.evidence[0].payload["resting_heart_rate"], 61.0)
            self.assertTrue(result.warnings)

    def test_daily_health_surfaces_requested_metrics_when_present(self) -> None:
        """日报必须直接显示心率、活动热量和血氧，缺失项仍不得补零。"""

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "health.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE health_payloads(id INTEGER PRIMARY KEY, received_at TEXT, payload_json TEXT)")
            zone = timezone(timedelta(hours=8))
            start = datetime(2026, 8, 29, tzinfo=zone)
            early_payload = {
                "active_calories": [{
                    "start_time": start.isoformat(),
                    "end_time": (start + timedelta(hours=10)).isoformat(),
                    "calories": 100,
                }],
            }
            payload = {
                "steps": [{"count": 6783}],
                "sleep": [{"duration_seconds": 5.5 * 3600}],
                "heart_rate": [{"bpm": 60}],
                "resting_heart_rate": [{"bpm": 45}],
                "active_calories": [{
                    "start_time": start.isoformat(),
                    "end_time": (start + timedelta(hours=20)).isoformat(),
                    "calories": 420,
                }],
                "oxygen_saturation": [{"percentage": 98}],
            }
            connection.executemany(
                "INSERT INTO health_payloads(received_at,payload_json) VALUES(?,?)",
                [
                    ((start + timedelta(hours=10)).isoformat(), json.dumps(early_payload)),
                    ((start + timedelta(hours=20)).isoformat(), json.dumps(payload)),
                ],
            )
            connection.commit()
            connection.close()
            result = HealthSource(
                database,
                ["steps", "sleep", "heart_rate", "resting_heart_rate", "active_calories", "oxygen_saturation", "exercise"],
            ).collect(TimeWindow(start, start + timedelta(hours=22)), None)
            fact = result.evidence[0].fact
            self.assertIn("步数 6783步", fact)
            self.assertIn("睡眠 5.5小时", fact)
            self.assertIn("平均心率 60.0次/分", fact)
            self.assertIn("静息心率 45.0次/分", fact)
            self.assertIn("活动热量 420千卡", fact)
            self.assertIn("血氧 98.0%", fact)
            self.assertNotIn("运动", fact)

    def test_user_md_detects_manual_change(self) -> None:
        """人工修改受管区块后，下一次同步必须停止。"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "USER.md"
            projection = UserMdProjection(path)
            projection.apply("当前状态 A")
            path.write_text(path.read_text(encoding="utf-8").replace("当前状态 A", "人工修改"), encoding="utf-8")
            with self.assertRaises(ValueError):
                projection.apply("当前状态 B")

    def test_weekly_health_reports_coverage_and_does_not_fill_missing_days(self) -> None:
        """周健康按天汇总，指标缺失日不得按零拉低日均。"""

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "health.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE health_payloads(id INTEGER PRIMARY KEY, received_at TEXT, payload_json TEXT)")
            zone = timezone(timedelta(hours=8))
            start = datetime(2026, 8, 24, tzinfo=zone)
            connection.executemany(
                "INSERT INTO health_payloads(received_at,payload_json) VALUES(?,?)",
                [
                    ((start + timedelta(hours=20)).isoformat(), json.dumps({"steps": [{"count": 6000}], "sleep": [{"duration_seconds": 7 * 3600}]})),
                    ((start + timedelta(days=1, hours=20)).isoformat(), json.dumps({"steps": [{"count": 8000}]})),
                ],
            )
            connection.commit()
            connection.close()
            result = HealthSource(database, ["steps", "sleep"]).collect(
                TimeWindow(start, start + timedelta(days=6, hours=22)), None
            )
            self.assertIn("设备覆盖 2/7 天", result.evidence[0].fact)
            self.assertIn("步数 2/7 天，日均 7000步", result.evidence[0].fact)
            self.assertIn("睡眠 1/7 天，日均 7小时", result.evidence[0].fact)

    def test_health_window_compares_real_instants_across_offsets(self) -> None:
        """UTC 快照跨上海午夜时必须按实际时刻归入正确业务日。"""

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "health.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE health_payloads(id INTEGER PRIMARY KEY, received_at TEXT, payload_json TEXT)")
            connection.execute(
                "INSERT INTO health_payloads(received_at,payload_json) VALUES(?,?)",
                ("2026-08-28T16:30:00+00:00", json.dumps({"steps": [{"count": 1234}]})),
            )
            connection.commit()
            connection.close()
            zone = timezone(timedelta(hours=8))
            start = datetime(2026, 8, 29, tzinfo=zone)
            result = HealthSource(database, ["steps"]).collect(TimeWindow(start, start + timedelta(days=1)), None)
            self.assertEqual(result.evidence[0].payload["steps"], 1234)

    def test_cumulative_health_record_keeps_maximum_for_same_interval(self) -> None:
        """同一睡眠会话的迟到局部更新不能覆盖已见完整时长。"""

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "health.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE health_payloads(id INTEGER PRIMARY KEY, received_at TEXT, payload_json TEXT)")
            end_time = "2026-08-29T00:00:00+00:00"
            connection.executemany(
                "INSERT INTO health_payloads(received_at,payload_json) VALUES(?,?)",
                [
                    ("2026-08-29T00:10:00+00:00", json.dumps({"sleep": [{"session_end_time": end_time, "duration_seconds": 7 * 3600}]})),
                    ("2026-08-29T00:20:00+00:00", json.dumps({"sleep": [{"session_end_time": end_time, "duration_seconds": 30 * 60}]})),
                ],
            )
            connection.commit()
            connection.close()
            zone = timezone(timedelta(hours=8))
            start = datetime(2026, 8, 29, tzinfo=zone)
            result = HealthSource(database, ["sleep"]).collect(TimeWindow(start, start + timedelta(days=1)), None)
            self.assertEqual(result.evidence[0].payload["sleep"], 7.0)

    def test_daily_health_does_not_fill_today_with_stale_metrics(self) -> None:
        """收到旧指标时只记录新鲜度，不把前一天值展示为今天。"""

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "health.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE health_payloads(id INTEGER PRIMARY KEY, received_at TEXT, payload_json TEXT)")
            zone = timezone(timedelta(hours=8))
            start = datetime(2026, 9, 13, tzinfo=zone)
            payload = {
                "steps": [{"count": 15426, "end_time": (start + timedelta(hours=20)).isoformat()}],
                "heart_rate": [{"bpm": 60, "time": (start - timedelta(hours=4)).isoformat()}],
                "oxygen_saturation": [{"percentage": 98, "time": (start - timedelta(hours=3)).isoformat()}],
            }
            connection.execute(
                "INSERT INTO health_payloads(received_at,payload_json) VALUES(?,?)",
                ((start + timedelta(hours=20)).isoformat(), json.dumps(payload)),
            )
            connection.commit()
            connection.close()

            result = HealthSource(database, ["steps", "heart_rate", "oxygen_saturation"]).collect(
                TimeWindow(start, start + timedelta(hours=22)), None
            )

            self.assertEqual(result.evidence[0].payload["steps"], 15426)
            self.assertNotIn("heart_rate", result.evidence[0].payload)
            self.assertNotIn("oxygen_saturation", result.evidence[0].payload)
            self.assertEqual(result.evidence[0].payload["freshness"]["heart_rate"]["last_event_date"], "2026-09-12")
            self.assertTrue(any("事件滞后" in warning for warning in result.warnings))


if __name__ == "__main__":
    unittest.main()
