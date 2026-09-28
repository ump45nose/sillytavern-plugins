import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from favsync.adapters_ext import XhsAdapter
from favsync.common import SyncError
from favsync.config import load
from favsync.engine import Engine
from favsync.store import Store


class IdleAdapter:
    def scan(self, source, cursor=0, start=None):
        return [], None


class RiskAdapter(IdleAdapter):
    def __init__(self):
        self.scans = 0

    def begin_run(self):
        pass

    def scan(self, source, cursor=0, start=None):
        self.scans += 1
        raise SyncError("verification_required")


class XhsSafetySmoke(unittest.TestCase):
    def config(self, directory):
        path = Path(directory) / "config.toml"
        path.write_text(
            f'state_dir="{directory}/state"\n'
            f'download_dir="{directory}/downloads"\n'
            '[xhs]\nmax_pages_per_run=2\nmax_new_items_per_run=5\n'
            'max_detail_items_per_run=5\nrequest_delay_min_seconds=0\n'
            'request_delay_max_seconds=0\ndetail_cache_ttl_seconds=86400\n'
        )
        cfg = load(path)
        cfg["storage"] = {"min_free_bytes": 0, "resume_free_bytes": 0}
        return cfg

    def test_seen_page_is_incremental_boundary_and_run_limit_is_shared(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            store = Store(cfg["state_dir"])
            try:
                Path(cfg["state_dir"], "xhs-cookies.json").write_text('{"a1":"fixture"}')
                store.source("xhs_favorites", "personal")
                with store.db:
                    for number in range(30):
                        store.db.execute("INSERT INTO seen VALUES(?,?,?,?,0)",
                                         ("xhs_favorites", "personal", str(number), 1))
                adapter = XhsAdapter(cfg, store)
                calls = []

                def command(argv, *_args):
                    calls.append(argv[0:2])
                    if argv[0] == "xhs" and argv[1] == "status":
                        return {"ok": True, "data": {"user": {"id": "account"}}}
                    return {"ok": True, "data": {"notes": [{"note_id": str(i)} for i in range(30)],
                                                   "has_more": True, "cursor": "next"}}

                with patch("favsync.adapters_ext._json_command", side_effect=command):
                    records, _ = adapter.scan("xhs_favorites")
                self.assertEqual(records, [])
                self.assertEqual(len(calls), 2)  # one status plus one already-seen page

                adapter.begin_run()
                with patch("favsync.adapters_ext._json_command", side_effect=[
                    {"ok": True, "data": {"user": {"id": "account"}}},
                    {"ok": True, "data": {"notes": [{"note_id": f"new-{i}"} for i in range(8)],
                                            "has_more": True, "cursor": "next"}},
                ]):
                    records, _ = adapter.scan("xhs_likes")
                self.assertEqual(len(records), 5)
            finally:
                store.close()

    def test_risk_error_sets_persistent_fuse(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            cfg["xhs_favorites"]["enabled"] = True
            risk = RiskAdapter()
            engine = Engine(cfg, {"telegram": IdleAdapter(), "x": IdleAdapter(), "xhs": risk})
            try:
                self.assertFalse(engine.cycle())
                self.assertEqual(engine.store.xhs_fuse("personal")["reason"], "verification_required")
                self.assertFalse(engine.cycle())
                self.assertEqual(risk.scans, 1)
                engine.store.clear_xhs_fuse("personal")
                self.assertFalse(engine.cycle())
                self.assertEqual(risk.scans, 2)
            finally:
                engine.store.close()

    def test_detail_cache_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state")
            try:
                store.save_xhs_detail("personal", "note", {"下载地址": ["https://example.invalid/a.jpg"]})
                self.assertIn("下载地址", store.xhs_detail("personal", "note", 60))
                store.delete_xhs_detail("personal", "note")
                self.assertIsNone(store.xhs_detail("personal", "note", 60))
            finally:
                store.close()

    def test_favorited_note_writes_one_markdown_with_local_media(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self.config(directory)
            engine = Engine(cfg)
            try:
                record = {"id": "note1", "text": "", "assets": [], "bundle": True,
                          "locator": {"url": "https://example.invalid/note1",
                                      "naming": {"group": "作者", "date": "2026-09-28"}}}
                engine.store.source("xhs_likes", "personal")
                engine.store.ingest("xhs_likes", "personal", [record])
                item = engine.store.pending("xhs_likes", "personal")[0]
                root = Path(cfg["xhs"]["output_dir"])
                root.mkdir(parents=True)
                engine.store.xhs_ordinal("personal", "作者", "2026-09-28", "note1")
                engine.store.xhs_stem("personal", "作者", "2026-09-28", "note1", "作者_2026-09-28_1", root)
                media = root / "作者_2026-09-28_1.jpg"
                media.write_bytes(b"image")
                engine.store.save_xhs_media(item, [media])
                engine.store.update_body(item, "笔记正文")
                engine.store.bundle_result(item)
                self.assertFalse(list(root.glob("*.md")))
                engine.store.source("xhs_favorites", "personal")
                engine.store.ingest("xhs_favorites", "personal", [record])
                self.assertTrue(engine.publish_markdown("xhs_favorites", "personal"))
                note = root / "作者_2026-09-28_1.md"
                self.assertIn("笔记正文", note.read_text())
                self.assertIn("![图片 1](", note.read_text())
                self.assertTrue(engine.publish_markdown("xhs_favorites", "personal"))
                self.assertEqual(len(list(root.glob("*.md"))), 1)
            finally:
                engine.store.close()


if __name__ == "__main__":
    unittest.main()
