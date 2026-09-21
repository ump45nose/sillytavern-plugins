import tempfile
from pathlib import Path
import unittest

from favsync.config import load
from favsync.store import Store
from favsync.cookies import cookie_header, netscape_for, eh_netscape
from favsync.adapters_ext import EhAdapter


class ExtendedSmoke(unittest.TestCase):
    def test_source_mapping_baseline_and_xhs_stable_ordinal(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.source("eh_favorites", "personal")
                record = {"id": "123", "text": "", "assets": [], "bundle": True, "locator": {"url": "fixture"}}
                store.ingest("eh_favorites", "personal", [record], baseline=True)
                self.assertEqual(store.db.execute("select count(*) from items").fetchone()[0], 0)
                store.source("xhs_likes", "personal")
                store.ingest("xhs_likes", "personal", [record])
                item = store.pending("xhs_likes", "personal")[0]
                self.assertEqual(item["platform"], "xhs")
                self.assertEqual(store.xhs_ordinal("personal", "作者", "2026-09-21", "123"), 1)
                self.assertEqual(store.xhs_ordinal("personal", "作者", "2026-09-21", "123"), 1)
                self.assertEqual(store.xhs_ordinal("personal", "作者", "2026-09-21", "124"), 2)
                output = Path(directory) / "xhs"
                output.mkdir()
                self.assertEqual(store.xhs_stem("personal", "作者", "2026-09-21", "123", "作者_2026-09-21_1", output),
                                 "作者_2026-09-21_1")
                self.assertEqual(store.xhs_stem("personal", "别名", "2026-09-21", "124", "作者_2026-09-21_1", output),
                                 "作者_2026-09-21_1_124")
                eh = Path(directory) / "eh"
                self.assertEqual(store.eh_path("personal", "123", "Artist", "Title", eh).name, "Title.zip")
                self.assertEqual(store.eh_path("personal", "124", "Artist", "Title", eh).name, "Title_[124].zip")
            finally:
                store.close()

    def test_cookie_domain_separation(self):
        data = {"cookie_data": {"all": [
            {"domain": ".xiaohongshu.com", "path": "/", "name": "a1", "value": "x"},
            {"domain": ".exhentai.org", "path": "/", "name": "ipb_member_id", "value": "1"},
            {"domain": ".exhentai.org", "path": "/", "name": "ipb_pass_hash", "value": "2"},
            {"domain": ".example.org", "path": "/", "name": "secret", "value": "no"}]}}
        self.assertEqual(cookie_header(data, ("xiaohongshu.com",), ("a1",)), "a1=x")
        jar = netscape_for(data, ("exhentai.org",), ("ipb_member_id", "ipb_pass_hash"))
        self.assertIn(b"ipb_member_id", jar)
        self.assertNotIn(b"secret", jar)
        mirrored = eh_netscape(data)
        self.assertIn(b".e-hentai.org", mirrored)
        self.assertIn(b".exhentai.org", mirrored)

    def test_config_defaults_extended_sources_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('state_dir="state"\ndownload_dir="downloads"\n')
            cfg = load(path)
            self.assertFalse(cfg["eh_favorites"]["enabled"])
            self.assertFalse(cfg["xhs_favorites"]["enabled"])
            self.assertEqual(cfg["storage"]["min_free_bytes"], 214748364800)

    def test_eh_gallery_dl_tag_shape(self):
        self.assertEqual(EhAdapter._tags({"tags": ["artist:Alice", "group:Circle"],
                                          "tags_character": ["Hero"]}),
                         {"artist": ["Alice"], "group": ["Circle"], "character": ["Hero"]})

    def test_execution_history_records_simple_results(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            try:
                store.record_execution("content", 1.0, True)
                store.record_execution("cookiecloud", 2.0, False)
                history = store.status()["execution_history"]
                self.assertEqual([(row["kind"], row["result"]) for row in history],
                                 [("cookiecloud", "failed"), ("content", "success")])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
