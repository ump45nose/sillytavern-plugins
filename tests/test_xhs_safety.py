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


if __name__ == "__main__":
    unittest.main()
