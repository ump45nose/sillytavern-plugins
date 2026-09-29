import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

from favsync.adapters_pixiv_wallabag import PixivAdapter, WallabagAdapter
from favsync.config import load
from favsync.store import Store


class PixivWallabagSmoke(unittest.TestCase):
    def _config(self, directory):
        path = Path(directory) / "config.toml"
        path.write_text(
            f'state_dir="{directory}/state"\n'
            f'download_dir="{directory}/downloads"\n'
            '[pixiv]\n'
            'uid="123"\n'
            f'refresh_token_file="{directory}/token"\n'
            f'picture_dir="{directory}/downloads/Pixiv/picture"\n'
            f'novel_dir="{directory}/downloads/Pixiv/noval"\n'
            'ugoira_enabled=false\n'
            'novel_embeds=true\n'
            '[wallabag]\n'
            f'output_dir="{directory}/downloads/Wallabag"\n'
            f'credentials_file="{directory}/wallabag.json"\n')
        return load(path)

    def test_pixiv_uses_declared_work_type_and_visibility(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._config(directory)
            adapter = PixivAdapter(cfg)
            captured = []
            adapter._events = lambda url: captured.append(url) or [
                [1, "", {"id": 42, "type": "manga", "count": 2, "title": "T",
                         "user": {"name": "A"}, "series": {"title": "S"}}]]
            records, _ = adapter.scan("pixiv_art_private")
            self.assertIn("rest=hide", captured[0])
            self.assertEqual(records[0]["locator"]["work_type"], "manga")
            self.assertEqual(records[0]["locator"]["count"], 2)

    def test_pixiv_eight_pages_become_valid_comic_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._config(directory)
            Path(cfg["pixiv"]["refresh_token_file"]).write_text("fixture-token")
            store = Store(cfg["state_dir"], initialize=True)
            try:
                adapter = PixivAdapter(cfg, store)
                meta = {"id": 42, "type": "manga", "count": 8, "title": "T",
                        "create_date": "2026-09-22T00:00:00Z", "user": {"name": "A"}}
                adapter._events = lambda url: [[2, "", meta], *[[3, "url", meta] for _ in range(8)]]

                def fake_command(argv, timeout, *args, **kwargs):
                    import json
                    config_path = Path(argv[argv.index("-c") + 1])
                    payload = json.loads(config_path.read_text())
                    destination = Path(payload["extractor"]["pixiv"]["base-directory"])
                    for page in range(8):
                        (destination / f"{page:04}.jpg").write_bytes(b"\xff\xd8\xfffixture")

                item = {"account": "personal", "item_id": "art:42",
                        "locator": '{"url":"https://www.pixiv.net/artworks/42",'
                                   '"work_id":"42","work_type":"manga","author":"A",'
                                   '"title":"T","series":"","count":8}'}
                staging = Path(directory) / "staging"; staging.mkdir()
                with patch("favsync.adapters_pixiv_wallabag.command", fake_command):
                    output = adapter.download_bundle(item, staging)
                self.assertEqual(len(output), 1)
                with zipfile.ZipFile(output[0]) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertEqual(len(archive.namelist()), 9)
                    self.assertIn("ComicInfo.xml", archive.namelist())
            finally:
                store.close()

    def test_wallabag_fingerprint_update_requeues_same_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, initialize=True)
            try:
                store.source("wallabag_entries", "personal")
                record = {"id": "7", "locator": {"fingerprint": "a", "title": "Old"}}
                store.ingest_wallabag("wallabag_entries", "personal", [record])
                item = store.db.execute("select * from items where platform='wallabag'").fetchone()
                filename = store.wallabag_path("personal", "7", "Old_[7].epub")
                store.wallabag_export_result("personal", "7", "a", "complete")
                store.bundle_result(item)
                record["locator"]["title"] = "Renamed"
                store.ingest_wallabag("wallabag_entries", "personal", [record])
                row = store.db.execute("select bundle_status from items where platform='wallabag'").fetchone()
                self.assertEqual(row[0], "done")
                record["locator"]["fingerprint"] = "b"
                store.ingest_wallabag("wallabag_entries", "personal", [record])
                row = store.db.execute("select bundle_status from items where platform='wallabag'").fetchone()
                self.assertEqual(row[0], "pending")
                self.assertEqual(store.wallabag_path("personal", "7", "Renamed_[7].epub"), filename)
            finally:
                store.close()

    def test_wallabag_invalid_content_stays_out_of_queue_until_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory, initialize=True)
            try:
                store.source("wallabag_entries", "personal")
                record = {"id": "4", "locator": {"fingerprint": "short", "title": "Chapter",
                                                  "invalid_content": True, "content_chars": 97}}
                store.ingest_wallabag("wallabag_entries", "personal", [record])
                self.assertEqual(list(store.pending("wallabag_entries", "personal")), [])
                store.ingest_wallabag("wallabag_entries", "personal", [record])
                self.assertEqual(list(store.pending("wallabag_entries", "personal")), [])
                row = store.db.execute("SELECT bundle_status,error FROM items WHERE item_id='4'").fetchone()
                self.assertEqual(tuple(row), ("skipped_invalid", "invalid_content"))
                record["locator"].update(fingerprint="repaired", invalid_content=False, content_chars=250)
                store.ingest_wallabag("wallabag_entries", "personal", [record])
                self.assertEqual([r["item_id"] for r in store.pending("wallabag_entries", "personal")], ["4"])
            finally:
                store.close()

    def test_epub_body_and_image_completeness_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "entry.epub"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mimetype", "application/epub+zip")
                archive.writestr("OEBPS/chapter.xhtml", "<html><body>" + "正文" * 100 +
                                 '<img src="https://example.test/image.jpg"></body></html>')
            self.assertEqual(WallabagAdapter._validate_epub(path, 100, 1), "incomplete")


if __name__ == "__main__":
    unittest.main()
