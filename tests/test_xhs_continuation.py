"""XHS continuation regression checks; temporary SQLite and stubbed list API only."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from favsync.adapters_ext import XhsAdapter
from favsync.common import SyncError
from favsync.config import load
from favsync.sources import ScanResult
from favsync.store import Store


class XhsContinuationTests(unittest.TestCase):
    source = "xhs_favorites"
    account = "personal"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        config = Path(temporary.name) / "config.toml"
        config.write_text('state_dir="state"\ndownload_dir="downloads"\n')
        self.cfg = load(config)
        self.cfg["xhs"].update(max_new_items_per_run=2, max_pages_per_run=2)
        self.store = Store(self.cfg["state_dir"], initialize=True)
        self.addCleanup(lambda: self.store.close())
        self.store.source(self.source, self.account)
        self.calls = []

    @staticmethod
    def page(ids, cursor=None):
        return {"ok": True, "data": {
            "notes": [{"note_id": item_id, "xsec_token": "token-" + item_id} for item_id in ids],
            "has_more": cursor is not None, "cursor": cursor}}

    def adapter(self):
        adapter = XhsAdapter(self.cfg, self.store)
        adapter.identity = lambda: "fixture"
        adapter._pace = lambda: None
        adapter._env = lambda: {}
        return adapter

    def scan(self, pages, *, commit=True, source=None):
        def command(argv, *_args):
            cursor = argv[argv.index("--cursor") + 1] if "--cursor" in argv else ""
            self.calls.append(cursor)
            return pages[cursor]
        source = source or self.source
        with patch("favsync.adapters_ext._json_command", side_effect=command):
            result = self.adapter().scan(source)
        if commit:
            self.store.apply_scan(source, self.account, result)
        return result

    def ids(self):
        return {row[0] for row in self.store.db.execute(
            "SELECT item_id FROM seen WHERE source=? AND account=?", (self.source, self.account))}

    def restart_store(self):
        self.store.close()
        self.store = Store(self.cfg["state_dir"])

    def test_partial_page_survives_restart_and_commits_only_selected_ids(self):
        self.store.update(self.source, self.account, cursor=731, baseline_at=42)
        first = self.scan({"": self.page(["a", "b", "c", "d", "e"])})
        self.assertEqual(first.reason, "request_budget")
        self.assertEqual(self.ids(), {"a", "b"})
        self.assertEqual([r["id"] for r in first.continuation["pending"]], ["c", "d", "e"])
        self.restart_store()
        second = self.scan({})
        self.assertEqual(second.reason, "request_budget")
        self.assertEqual(self.ids(), {"a", "b", "c", "d"})
        third = self.scan({})
        self.assertEqual(third.reason, "end")
        self.assertEqual(self.ids(), {"a", "b", "c", "d", "e"})
        self.assertEqual(self.calls, [""])
        self.assertIsNone(self.store.scan_continuation(self.source, self.account))
        state = self.store.source(self.source, self.account)
        self.assertEqual((state["cursor"], state["baseline_at"], state["scan_status"]), (731, 42, "complete"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM items").fetchone()[0], 5)

    def test_page_limit_resumes_next_page_instead_of_seen_head(self):
        self.cfg["xhs"].update(max_new_items_per_run=20, max_pages_per_run=1)
        self.assertEqual(self.scan({"": self.page(["a", "b"], "page2")}).reason, "page_limit")
        self.restart_store()
        result = self.scan({"page2": self.page(["c", "d"])})
        self.assertTrue(result.complete)
        self.assertEqual(self.calls, ["", "page2"])
        self.assertEqual(self.ids(), {"a", "b", "c", "d"})

    def test_exact_item_budget_saves_next_page_cursor(self):
        first = self.scan({"": self.page(["a", "b"], "page2")})
        self.assertEqual(first.reason, "request_budget")
        self.assertEqual(first.continuation["cursor"], "page2")
        self.assertEqual(first.continuation["pending"], [])
        self.scan({"page2": self.page(["c"])})
        self.assertEqual(self.ids(), {"a", "b", "c"})

    def test_head_inserts_do_not_hide_unread_page_or_starve_buffered_items(self):
        self.scan({"": self.page(["a", "b", "c"], "3")})
        # New x/y at head move previously saved a/b into offset page 3. The
        # buffered c is consumed first; b/c are not the historical boundary.
        result = self.scan({"3": self.page(["b", "c", "d"], "6")})
        self.assertEqual(result.reason, "request_budget")
        self.assertEqual(self.ids(), {"a", "b", "c", "d"})
        self.scan({"6": self.page(["e"])})
        self.assertEqual(self.ids(), {"a", "b", "c", "d", "e"})
        # Once the old window ends, a fresh head pass catches the new arrivals.
        self.scan({"": self.page(["x", "y", "a"], "3")})
        self.assertEqual(self.ids(), {"a", "b", "c", "d", "e", "x", "y"})
        self.assertEqual(self.calls, ["", "3", "6", ""])

    def test_repeated_newly_seen_page_is_not_boundary_even_with_equal_timestamps(self):
        self.cfg["xhs"].update(max_new_items_per_run=20, max_pages_per_run=1)
        with patch("time.time", return_value=100):
            self.scan({"": self.page(["a", "b"], "2")})
            repeated = self.scan({"2": self.page(["a", "b"], "4")})
            self.assertEqual(repeated.reason, "page_limit")
            self.scan({"4": self.page(["c"])})
        self.assertEqual(self.ids(), {"a", "b", "c"})
        self.assertEqual(self.calls, ["", "2", "4"])

    def test_historical_boundary_and_retry_locator_keep_identity_and_names(self):
        record = XhsAdapter._note({"note_id": "old", "xsec_token": "expired", "user": {"nickname": "Original"}})
        with patch("time.time", return_value=50):
            self.store.ingest(self.source, self.account, [record])
        self.store.save_xhs_detail(self.account, "old", {"stale": True})
        original = self.store.db.execute("SELECT * FROM seen").fetchone()
        with patch("time.time", return_value=100):
            result = self.scan({"": self.page(["old"], "unused")})
        self.assertEqual(result.reason, "seen_boundary")
        self.assertEqual([r["id"] for r in result.records], ["old"])
        self.assertEqual(tuple(self.store.db.execute("SELECT * FROM seen").fetchone()), tuple(original))
        locator = json.loads(self.store.pending(self.source, self.account)[0]["locator"])
        self.assertIn("xsec_token=token-old", locator["url"])
        self.assertEqual(locator["naming"], record["locator"]["naming"])
        self.assertIsNone(self.store.xhs_detail(self.account, "old", 86400))

    def test_checkpoint_and_queue_roll_back_together_when_checkpoint_write_fails(self):
        self.scan({"": self.page(["a", "b", "c", "d", "e"])})
        before = self.store.scan_continuation(self.source, self.account)
        source_before = self.store.source(self.source, self.account)
        result = self.scan({}, commit=False)
        self.store.db.execute("""CREATE TEMP TRIGGER reject_checkpoint BEFORE INSERT ON settings
            WHEN NEW.key LIKE 'scan_continuation:%'
            BEGIN SELECT RAISE(ABORT, 'fixture checkpoint failure'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fixture checkpoint failure"):
            self.store.apply_scan(self.source, self.account, result)
        self.assertEqual(self.ids(), {"a", "b"})
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM items").fetchone()[0], 2)
        self.assertEqual(self.store.scan_continuation(self.source, self.account), before)
        self.assertEqual(self.store.source(self.source, self.account), source_before)
        self.store.db.execute("DROP TRIGGER reject_checkpoint")
        self.store.apply_scan(self.source, self.account, result)
        self.assertEqual(self.ids(), {"a", "b", "c", "d"})

    def test_checkpoint_clear_and_final_batch_are_atomic(self):
        self.scan({"": self.page(["a", "b", "c"])})
        before = self.store.scan_continuation(self.source, self.account)
        result = self.scan({}, commit=False)
        self.store.db.execute("""CREATE TEMP TRIGGER reject_clear BEFORE DELETE ON settings
            WHEN OLD.key LIKE 'scan_continuation:%'
            BEGIN SELECT RAISE(ABORT, 'fixture clear failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.apply_scan(self.source, self.account, result)
        self.assertEqual(self.ids(), {"a", "b"})
        self.assertEqual(self.store.scan_continuation(self.source, self.account), before)
        self.assertEqual(self.store.source(self.source, self.account)["scan_status"], "partial")

    def test_scan_without_commit_does_not_advance_continuation(self):
        self.scan({"": self.page(["a", "b", "c", "d"])})
        before = self.store.scan_continuation(self.source, self.account)
        self.scan({}, commit=False)
        self.restart_store()
        self.assertEqual(self.store.scan_continuation(self.source, self.account), before)
        self.scan({})
        self.assertEqual(self.ids(), {"a", "b", "c", "d"})

    def test_api_failure_preserves_saved_window_for_retry(self):
        self.cfg["xhs"].update(max_new_items_per_run=20, max_pages_per_run=1)
        self.scan({"": self.page(["a"], "next")})
        before = self.store.scan_continuation(self.source, self.account)
        with self.assertRaisesRegex(SyncError, "rate_limited"):
            self.scan({"next": {"ok": False, "error": {"code": "429"}}})
        self.assertEqual(self.store.scan_continuation(self.source, self.account), before)
        self.scan({"next": self.page(["b"])})
        self.assertEqual(self.ids(), {"a", "b"})

    def test_repeated_cursor_across_runs_fails_without_discarding_checkpoint(self):
        self.cfg["xhs"].update(max_new_items_per_run=20, max_pages_per_run=1)
        self.scan({"": self.page(["a"], "next")})
        before = self.store.scan_continuation(self.source, self.account)
        with self.assertRaisesRegex(SyncError, "scan_incomplete"):
            self.scan({"next": self.page(["b"], "next")})
        self.assertEqual(self.ids(), {"a"})
        self.assertEqual(self.store.scan_continuation(self.source, self.account), before)

    def test_continuation_is_source_and_account_scoped(self):
        self.scan({"": self.page(["a", "b", "c"])})
        favorite = self.store.scan_continuation(self.source, self.account)
        self.store.source("xhs_likes", self.account)
        self.scan({"": self.page(["like"])}, source="xhs_likes")
        self.assertEqual(self.store.scan_continuation(self.source, self.account), favorite)
        self.assertIsNone(self.store.scan_continuation(self.source, "other"))
        self.assertIsNone(self.store.scan_continuation("xhs_likes", self.account))

    def test_apply_scan_preserves_tuple_contract_and_filtered_records(self):
        self.assertEqual(tuple(ScanResult([], 12, "page_limit", {"cursor": "opaque"})), ([], 12))
        record = XhsAdapter._note({"note_id": "a"})
        result = ScanResult([record], cursor=18, reason="request_budget", continuation={"cursor": "opaque"})
        self.store.apply_scan(self.source, self.account, result, records=[], start_date="kept")
        state = self.store.source(self.source, self.account)
        self.assertEqual((state["cursor"], state["start_date"], state["scan_status"], state["scan_reason"]),
                         (18, "kept", "partial", "request_budget"))
        self.assertEqual(self.ids(), set())

    def test_malformed_continuation_fails_closed_without_reading_or_writing(self):
        valid = {"version": 1, "started_at": 100, "cursor": "next", "pending": [], "seen_cursors": ["next"]}
        malformed = ["invalid json", "[]", json.dumps({}), json.dumps({**valid, "pending": [{}]}),
                     json.dumps({**valid, "seen_cursors": [[]]}),
                     json.dumps({**valid, "started_at": float("nan")}),
                     json.dumps({key: value for key, value in valid.items() if key != "cursor"})]
        key = f"scan_continuation:{self.source}:{self.account}"
        for value in malformed:
            with self.subTest(value=value):
                self.store.setting(key, value)
                with self.assertRaisesRegex(SyncError, "scan_incomplete"):
                    self.scan({})
                self.assertEqual(self.store.setting(key), value)
                self.assertEqual(self.ids(), set())
        self.assertEqual(self.calls, [])

    def test_incomplete_baseline_is_rejected_before_any_ingestion(self):
        self.store.source("x_likes", self.account)
        result = ScanResult([XhsAdapter._note({"note_id": "old"})], reason="page_limit")
        with self.assertRaisesRegex(SyncError, "scan_incomplete"):
            self.store.apply_scan("x_likes", self.account, result, baseline=True)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM seen").fetchone()[0], 0)
        self.assertIsNone(self.store.source("x_likes", self.account)["baseline_at"])

    def test_baseline_ingest_still_creates_only_seen_and_keeps_earlier_rows(self):
        self.store.source("x_likes", self.account)
        record = XhsAdapter._note({"note_id": "old"})
        self.store.apply_scan("x_likes", self.account, ScanResult([record]), baseline=True)
        before = tuple(self.store.db.execute("SELECT * FROM seen").fetchone())
        self.store.apply_scan("x_likes", self.account, ScanResult([record]))
        self.assertEqual(tuple(self.store.db.execute("SELECT * FROM seen").fetchone()), before)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM items").fetchone()[0], 0)
        self.assertIsNotNone(self.store.source("x_likes", self.account)["baseline_at"])


if __name__ == "__main__":
    unittest.main()
