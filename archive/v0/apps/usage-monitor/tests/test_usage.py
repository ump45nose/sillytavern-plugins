from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from usage_monitor_mcp.config import Settings
from usage_monitor_mcp.daily_events import DailyUsageProducer
from usage_monitor_mcp.reports import ReportStore, build_report, report_page
from usage_monitor_mcp.time_window import Window
from usage_monitor_mcp.token_usage import aggregate_tokens
from usage_monitor_mcp.traffic_usage import read_traffic


NOW = datetime.fromisoformat("2026-10-05T23:00:00+08:00")


def record(day="2026-10-05", zone="Asia/Taipei", tokens=100):
    next_day = "2026-10-06" if day == "2026-10-05" else "2026-10-05"
    return {"updatedAt": day + "T22:58:00+08:00", "receivedAt": day + "T22:59:00+08:00",
            "periodWindows": {"timeZone": zone, "today": {"key": day, "endsAt": next_day + "T00:00:00+08:00"}},
            "periods": {"today": {"totalTokens": tokens, "costUsd": 1.2,
                                     "clients": {"codex": tokens}, "clientCosts": {"codex": 1.2},
                                     "models": {"model-a": tokens}, "modelCosts": {"model-a": 1.2}}},
            "history": {"daily": []}, "limits": {"providers": [{"provider": "codex", "windows": []}]}}


class TokenDateTests(unittest.TestCase):
    def test_expired_and_different_calendar_are_not_counted(self):
        document = {"devices": {"fresh": record(), "same-offset": record(zone="Asia/Shanghai", tokens=40),
                                "stale-prior-day": record("2026-10-04", tokens=900),
                                "different-offset": record(zone="America/New_York", tokens=700)}}
        result = aggregate_tokens(document, Window.make(now=NOW))
        self.assertEqual(result["totals"]["tokens"], 140)
        self.assertEqual(result["models"][0]["tokens"], 140)
        self.assertEqual(result["tools"][0]["tokens"], 140)
        self.assertEqual(len(result["coverage"]["excluded_devices"]), 2)
        self.assertIn("stale-prior-day", result["coverage"]["stale_devices"])

    def test_historical_lookup_uses_only_exact_day(self):
        source = record(tokens=5000)
        source["history"]["daily"] = [
            {"date": "2026-10-03", "tokens": 8000, "cost": 8},
            {"date": "2026-10-04", "tokens": 75, "perModel": {"model-a": {"tokens": 75}},
             "perClient": {"codex": {"tokens": 75}}}]
        result = aggregate_tokens({"devices": {"a": source}}, Window.make("2026-10-04", now=NOW))
        self.assertEqual(result["totals"]["tokens"], 75)
        self.assertIsNone(result["totals"]["estimated_cost_usd"])
        self.assertEqual(result["devices"][0]["basis"], "history.daily")
        self.assertTrue(result["devices"][0]["finalized_day"])

    def test_unknown_limit_and_actual_cost_are_not_zero(self):
        result = aggregate_tokens({"devices": {"a": record()},
                                   "subscriptions": {"subscriptions": []}}, Window.make(now=NOW))
        self.assertEqual(result["limits_snapshot"][0]["status"], "unknown")
        self.assertEqual(result["limits_snapshot"][0]["windows"], [])
        self.assertEqual(result["subscriptions"]["status"], "not_configured")
        self.assertIsNone(result["subscriptions"]["actual_paid_today"])

    def test_same_day_stale_snapshot_is_retained_but_partial(self):
        source = record()
        source["receivedAt"] = "2026-10-05T15:00:00+08:00"
        source["updatedAt"] = "2026-10-05T15:00:00+08:00"
        result = aggregate_tokens({"devices": {"a": source}}, Window.make(now=NOW))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["totals"]["tokens"], 100)
        self.assertTrue(result["devices"][0]["stale"])

    def test_missing_or_duplicate_history_fails_closed(self):
        source = record()
        source["periodWindows"].pop("timeZone")
        source["history"]["daily"] = [{"date": "2026-10-04", "tokens": 75}]
        result = aggregate_tokens({"devices": {"a": source}}, Window.make("2026-10-04", now=NOW))
        self.assertIsNone(result["totals"]["tokens"])
        source["periodWindows"]["timeZone"] = "Asia/Taipei"
        source["history"]["daily"] *= 2
        result = aggregate_tokens({"devices": {"a": source}}, Window.make("2026-10-04", now=NOW))
        self.assertEqual(result["devices"][0]["basis"], "duplicate_history_dates")

    def test_bad_and_future_dates_are_rejected(self):
        for value in ("2026-10-06", "2026-02-30", "20261005", "../../secret"):
            with self.assertRaises(ValueError):
                Window.make(value, now=NOW)


def traffic_database(path):
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE traffic_hourly (bucket TEXT,category TEXT,pool TEXT,source_tag TEXT,exit_node TEXT,
                                upload_bytes INTEGER,download_bytes INTEGER);
    CREATE TABLE collector_gaps (started_at TEXT,ended_at TEXT,reason TEXT);
    CREATE TABLE collector_meta (key TEXT,value TEXT);
    """)
    con.executemany("INSERT INTO traffic_hourly VALUES(?,?,?,?,?,?,?)", [
        ("2026-10-04T23:00", "A", "p", "s", "n1", 900, 900),
        ("2026-10-05T00:00", "A", "p", "s", "n1", 20, 30),
        ("2026-10-05T22:00", "B", "p", "s", "n2", 40, 60),
        ("2026-10-05T23:00", "B", "p", "s", "n2", 800, 800)])
    con.execute("INSERT INTO collector_gaps VALUES(?,?,?)",
                ("2026-10-04T23:55:00+08:00", "2026-10-05T00:10:00+08:00", "test gap"))
    con.execute("INSERT INTO collector_meta VALUES(?,?)", ("last_sample", "2026-10-05T23:00:00+08:00"))
    con.commit()
    con.close()


class TrafficTests(unittest.TestCase):
    def test_daily_bytes_and_cross_day_gap_are_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "traffic.sqlite3"
            traffic_database(path)
            before = path.read_bytes()
            result = read_traffic(Settings(traffic_db=path), Window.make(now=NOW))
            self.assertEqual(result["totals"]["total_bytes"], 150)
            self.assertEqual(result["totals"]["upload_bytes"], 60)
            self.assertEqual(result["coverage"]["known_gap_seconds"], 600)
            self.assertIsNone(result["coverage"]["exact_sample_coverage_percent"])
            for dimension in result["dimensions"].values():
                self.assertEqual(sum(row["total_bytes"] for row in dimension), 150)
            self.assertEqual(path.read_bytes(), before)

    def test_unavailable_sources_do_not_create_zero_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(token_data_file=Path(directory) / "missing.json",
                                traffic_db=Path(directory) / "missing.sqlite3")
            result = build_report(settings, now=NOW)
            self.assertEqual(result["token_monitor"]["status"], "unavailable")
            self.assertIsNone(result["token_monitor"]["totals"]["tokens"])
            self.assertIsNone(result["shellcrash"]["totals"])
            self.assertFalse(settings.traffic_db.exists())


def minimal_report(settings, day, now):
    return {"schema_version": 1, "report_id": "usage-" + day, "window": Window.make(day, now=now).metadata(),
            "token_monitor": {"status": "ok", "totals": {"tokens": 120}, "models": [], "tools": [],
                              "devices": [], "subscriptions": {"status": "not_configured"}},
            "shellcrash": {"status": "ok", "totals": {"total_bytes": 300}, "dimensions": {}}}


class FakeEvents:
    def __init__(self):
        self.calls = []
        self.fail_next = False

    def register_event(self, *args):
        pass

    async def publish(self, name, data, **kwargs):
        self.calls.append((name, copy.deepcopy(data), kwargs))
        if self.fail_next:
            self.fail_next = False
            raise OSError("temporary")
        return {"queued": 1, "duplicate": False}


class PersistenceTests(unittest.TestCase):
    def test_report_is_immutable_and_page_inputs_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ReportStore(Path(directory))
            report = minimal_report(None, "2026-10-05", NOW)
            store.save_once(report)
            report["token_monitor"]["totals"]["tokens"] = 800
            self.assertEqual(store.save_once(report)["token_monitor"]["totals"]["tokens"], 120)
            self.assertEqual(store.list()["total"], 1)
            with self.assertRaises(ValueError):
                store.get("../../private")
            with self.assertRaises(ValueError):
                report_page(report, "summary", limit=1001)
            with self.assertRaises(ValueError):
                report_page(report, "arbitrary_section")

    def test_schedule_once_and_restart_do_not_repeat_or_replay_history(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings(), data_dir=Path(directory), events_enabled=True, event_subject="owner")
            events = FakeEvents()
            producer = DailyUsageProducer(events, settings, minimal_report)
            asyncio.run(producer.run_once(NOW.replace(hour=22)))
            self.assertEqual(len(events.calls), 0)
            asyncio.run(producer.run_once(NOW))
            asyncio.run(DailyUsageProducer(events, settings, minimal_report).run_once(NOW))
            self.assertEqual(len(events.calls), 1)
            self.assertEqual(events.calls[0][2]["event_id"], "usage.daily_ready:2026-10-05")

    def test_publish_retry_reuses_archived_payload_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(Settings(), data_dir=Path(directory), events_enabled=True, event_subject="owner")
            events = FakeEvents()
            events.fail_next = True
            producer = DailyUsageProducer(events, settings, minimal_report)
            with self.assertRaises(OSError):
                asyncio.run(producer.run_once(NOW))
            asyncio.run(producer.run_once(NOW.replace(minute=5)))
            self.assertEqual(events.calls[0], events.calls[1])


if __name__ == "__main__":
    unittest.main()
