"""Offline regression cases for FS2 and FS4–6; no account APIs are used."""
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from favsync.adapters import TelegramAdapter
from favsync.adapters_pixiv_wallabag import PixivAdapter
from favsync.common import SyncError
from favsync.config import load
from favsync.engine import Engine
from favsync.layout import paths


def record(item_id="1", assets=((1, "001.bin"),)):
    return {"id": item_id, "text": "fixture", "assets": assets, "locator": {}}


class CorrectnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / "config.toml"
        config.write_text('state_dir="state"\ndownload_dir="downloads"\n')
        self.cfg = load(config)
        self.cfg["storage"] = {"min_free_bytes": 0, "resume_free_bytes": 0}
        self.engine = Engine(self.cfg)
        self.addCleanup(self.engine.store.close)

    def pixiv_events(self, events):
        def command(argv, timeout, output, **kwargs):
            output.write(json.dumps(events).encode())
        return patch("favsync.adapters_pixiv_wallabag.command", command)

    def test_pixiv_mixed_terminal_errors_never_finish_baseline(self):
        self.cfg["pixiv"].update(uid="123", start_date="2020-01-01")
        self.cfg["pixiv_art_public"]["enabled"] = True
        normal = [2, "", {"id": 42, "title": "A", "type": "illust", "count": 1}]
        for error, expected in (("AuthenticationError", "auth_required"),
                                ("AuthorizationError", "auth_required"),
                                ("HttpError", "scan_incomplete"),
                                ("ConnectionError", "scan_incomplete"),
                                ("NotFoundError", "scan_incomplete")):
            with self.subTest(error=error), self.pixiv_events([normal, [-1, {"error": error}]]):
                self.assertFalse(self.engine.cycle("pixiv_art_public"))
            state = self.engine.store.source("pixiv_art_public", "personal")
            self.assertIsNone(state["baseline_at"])
            self.assertEqual(state["error"], expected)
            self.assertEqual(self.engine.store.db.execute("SELECT count(*) FROM seen").fetchone()[0], 0)

    def test_pixiv_invisible_work_and_normal_completion_preserve_baseline(self):
        self.cfg["pixiv"].update(uid="123", start_date="2020-01-01")
        self.cfg["pixiv_art_public"]["enabled"] = True
        # The pinned extractor emits count=0 metadata for deleted/locked works.
        events = [[2, "", {"id": 41, "count": 0}], [2, "", {"id": 42, "count": 1}]]
        with self.pixiv_events(events):
            self.assertTrue(self.engine.cycle("pixiv_art_public"))
        state = self.engine.store.source("pixiv_art_public", "personal")
        baseline = state["baseline_at"]
        seen = [tuple(row) for row in self.engine.store.db.execute("SELECT * FROM seen ORDER BY item_id")]
        with self.pixiv_events([events[1], [-1, {"error": "HttpError"}]]):
            self.assertFalse(self.engine.cycle("pixiv_art_public"))
        self.assertEqual(self.engine.store.source("pixiv_art_public", "personal")["baseline_at"], baseline)
        self.assertEqual([tuple(row) for row in self.engine.store.db.execute("SELECT * FROM seen ORDER BY item_id")], seen)

    def test_pixiv_rejects_nonlist_export(self):
        self.cfg["pixiv"]["uid"] = "123"
        with self.pixiv_events({"error": "fixture"}), self.assertRaisesRegex(SyncError, "invalid_export"):
            PixivAdapter(self.cfg)._events("https://example.test")

    def queue_asset(self):
        self.engine.store.source("telegram", "personal")
        self.engine.store.ingest("telegram", "personal", [record()])
        item = self.engine.store.pending("telegram", "personal")[0]
        asset = self.engine.store.assets(item)[0]
        final = paths(self.cfg, item, asset)
        final.parent.mkdir(parents=True, exist_ok=True)
        return item, asset, final

    def test_existing_zero_or_nonregular_target_is_not_done_or_overwritten(self):
        item, asset, final = self.queue_asset()
        class NoDownload:
            def download(self, *_args):
                raise AssertionError("unknown final must not be overwritten")
        final.write_bytes(b"")
        self.assertFalse(self.engine.drain("telegram", "personal", NoDownload()))
        self.assertEqual(final.read_bytes(), b"")
        state = self.engine.store.assets(item)[0]
        self.assertEqual((state["status"], state["error"]), ("failed", "existing_file_invalid"))
        final.unlink()
        other = self.root / "other"; other.write_bytes(b"keep")
        final.symlink_to(other)
        self.engine.attempted.clear()
        self.assertFalse(self.engine.drain("telegram", "personal", NoDownload()))
        self.assertEqual(other.read_bytes(), b"keep")

    def test_fresh_zero_file_fails_and_valid_existing_file_recovers(self):
        item, asset, final = self.queue_asset()
        class Empty:
            def download(self, item, asset, staging):
                target = staging / asset["filename"]; target.write_bytes(b""); return target
        self.assertFalse(self.engine.drain("telegram", "personal", Empty()))
        self.assertFalse(final.exists())
        self.assertEqual(self.engine.store.assets(item)[0]["error"], "download_missing_file")
        final.write_bytes(b"previous completed publication")
        self.engine.attempted.clear()
        self.assertTrue(self.engine.drain("telegram", "personal", Empty()))
        self.assertEqual(self.engine.store.assets(item)[0]["status"], "done")

    def test_new_publication_does_not_clobber_racing_final(self):
        item, asset, final = self.queue_asset()
        class Racing:
            def download(self, item, asset, staging):
                final.write_bytes(b"other writer")
                target = staging / asset["filename"]; target.write_bytes(b"download"); return target
        self.assertFalse(self.engine.drain("telegram", "personal", Racing()))
        self.assertEqual(final.read_bytes(), b"other writer")
        self.assertEqual(self.engine.store.assets(item)[0]["error"], "destination_exists")
        self.engine.attempted.clear()
        self.assertFalse(self.engine.drain("telegram", "personal", Racing()))
        self.assertEqual(self.engine.store.assets(item)[0]["status"], "failed")

    def test_publication_before_db_failure_recovers_without_redownload(self):
        item, asset, final = self.queue_asset()
        class Download:
            calls = 0
            def download(self, item, asset, staging):
                self.calls += 1
                target = staging / asset["filename"]; target.write_bytes(b"complete"); return target
        adapter = Download()
        with patch.object(self.engine.store, "asset_result", side_effect=sqlite3.OperationalError("busy")):
            with self.assertRaises(sqlite3.OperationalError):
                self.engine.drain("telegram", "personal", adapter)
        self.assertEqual(final.read_bytes(), b"complete")
        self.engine.attempted.clear()
        self.assertTrue(self.engine.drain("telegram", "personal", adapter))
        self.assertEqual(adapter.calls, 1)

    def test_session_busy_stops_same_account_assets_and_notice_only(self):
        self.cfg["telegram"].update(enabled=True, start_date="2020-01-01", accounts=[{"account": "second"}])
        self.cfg["telegram_notice"]["enabled"] = True
        class Adapter:
            def __init__(self, failure=None):
                self.scans = []; self.downloads = []; self.failure = failure
            def scan(self, source, **kwargs):
                self.scans.append(source)
                return [record("1", ((1, "001.bin"), (2, "002.bin"))), record("2")], 2
            def download(self, item, asset, staging):
                self.downloads.append((item["item_id"], asset["number"]))
                if self.failure:
                    raise SyncError(self.failure)
                target = staging / asset["filename"]; target.write_bytes(b"complete"); return target
        primary, second = Adapter("telegram_session_in_use"), Adapter()
        self.engine.adapters.update({"telegram": primary, "telegram:second": second})
        self.assertFalse(self.engine.cycle())
        self.assertEqual(primary.scans, ["telegram"])
        self.assertEqual(primary.downloads, [("1", 1)])
        self.assertEqual(len(second.downloads), 3)
        self.assertEqual(self.engine.store.source("telegram_notice", "personal")["error"], "telegram_session_in_use")

    def test_notice_identity_is_subject_and_changed_user_cannot_advance_cursor(self):
        self.cfg["telegram_notice"]["enabled"] = True
        self.engine.store.setting("tg_identity:telegram_notice:personal", "456")
        identity, message = "123", 10
        def export(argv, timeout):
            target = Path(argv[argv.index("-o") + 1])
            if "-c" not in argv:
                self.assertEqual(argv[argv.index("-i") + 1], "0")
                data = {"id": identity, "messages": []}
            else:
                data = {"id": 456, "messages": [{"id": message, "date": int(time.time()) + 1,
                         "text": "fixture", "raw": {"Out": True}}]}
            target.write_text(json.dumps(data))
        with patch("favsync.adapters.command", export):
            self.assertTrue(self.engine.cycle("telegram_notice"))
        self.assertEqual(self.engine.store.setting("tg_identity:personal"), "123")
        self.assertEqual(self.engine.store.setting("tg_identity:telegram_notice:personal"), "456")
        identity, message = "999", 11
        with patch("favsync.adapters.command", export):
            self.assertFalse(self.engine.cycle("telegram_notice"))
        state = self.engine.store.source("telegram_notice", "personal")
        self.assertEqual((state["cursor"], state["error"]), (10, "telegram_account_changed"))
        self.assertEqual(self.engine.store.db.execute("SELECT count(*) FROM seen").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
