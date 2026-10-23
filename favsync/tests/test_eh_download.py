"""Original-byte, resume and timeout checks without network access."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from favsync.common import SyncError

try:
    from gallery_dl import config, exception, job, output
    from favsync.eh_download import OriginalExtractor, OriginalDownloadJob, download_gallery
except ImportError:
    OriginalExtractor = None

IMAGE = b"\xff\xd8\xfffixture original bytes"
DIGEST = hashlib.sha1(IMAGE).hexdigest()
URL = "https://exhentai.org/g/123/0123456789/"


@unittest.skipIf(OriginalExtractor is None, "gallery extra is not installed")
class DownloadProgressTests(unittest.TestCase):
    def process(self, script):
        popen = subprocess.Popen
        def start(argv, **kwargs):
            self.child = popen([sys.executable, "-u", "-c", script], **kwargs)
            return self.child
        return patch("favsync.eh_download.subprocess.Popen", side_effect=start)

    def test_completed_pages_extend_the_deadline_beyond_total_timeout(self):
        script = '''
import json,time
print(json.dumps(["meta", {"filecount": 4}]), flush=True)
for page in range(1,5):
    time.sleep(.15)
    print(json.dumps(["page",page]),flush=True)
print(json.dumps(["done",None]),flush=True)
'''
        started = time.monotonic()
        with self.process(script):
            self.assertEqual(download_gallery("config", URL, .4), {"filecount": 4})
        self.assertGreater(time.monotonic() - started, .4)

    def test_stalled_child_times_out_and_is_reaped(self):
        with self.process('import time; time.sleep(10)'):
            with self.assertRaisesRegex(SyncError, "command_timeout"):
                download_gallery("config", URL, .2)
        self.assertIsNotNone(self.child.poll())

    def test_failures_and_incomplete_pages_never_complete(self):
        for events, code in (([["error", "original_unavailable"]], "original_unavailable"),
                             ([["meta", {"filecount": 2}], ["page", 1]], "incomplete_gallery"),
                             ([["meta", {"filecount": 2}], ["page", 2], ["done", None]], "incomplete_gallery")):
            with self.subTest(code=code), self.process(f"print({''.join(json.dumps(e)+chr(10) for e in events)!r},end='',flush=True)"):
                with self.assertRaisesRegex(SyncError, code):
                    download_gallery("config", URL, 2)

    def test_unknown_warnings_remain_errors(self):
        events = [["meta", {"filecount": 1}], ["page", 1], ["done", None]]
        script = ("import sys\nprint('[exhentai][warning] 429 rate limit',file=sys.stderr)\n"
                  + f"print({''.join(json.dumps(e)+chr(10) for e in events)!r},end='',flush=True)")
        with self.process(script), self.assertRaisesRegex(SyncError, "rate_limited"):
            download_gallery("config", URL, 2)

    def test_recovered_http_retries_require_complete_verified_pages(self):
        for complete in (True, False):
            events = [["meta", {"filecount": 1}], ["page", 1]]
            if complete:
                events.append(["done", None])
            script = ("import sys\nprint('[downloader.http][warning] SSLError retry',file=sys.stderr)\n"
                      + f"print({''.join(json.dumps(e)+chr(10) for e in events)!r},end='',flush=True)")
            with self.subTest(complete=complete), self.process(script):
                if complete:
                    self.assertEqual(download_gallery("config", URL, 2), {"filecount": 1})
                else:
                    with self.assertRaisesRegex(SyncError, "incomplete_gallery"):
                        download_gallery("config", URL, 2)


@unittest.skipIf(OriginalExtractor is None, "gallery extra is not installed")
class OriginalBytesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "0001.jpg"
        self.path.write_bytes(IMAGE)
        self.task = OriginalDownloadJob.__new__(OriginalDownloadJob)
        self.task.extractor = SimpleNamespace(original=True)
        self.task.pathfmt = SimpleNamespace(realpath=str(self.path))
        self.task.status = 0

    def test_native_original_is_accepted_by_sha1_without_fullimg_url(self):
        with patch.object(job.DownloadJob, "handle_url") as transport, \
                patch("favsync.eh_download.emit") as emit:
            self.task.handle_url("https://node.hath.network/native.jpg",
                                 {"num": 1, "_original_sha1": DIGEST})
        transport.assert_called_once()
        emit.assert_called_once_with("page", 1)

    def test_missing_proof_and_disabled_original_stop_before_download(self):
        for original, digest in ((True, None), (False, DIGEST)):
            self.task.extractor.original = original
            with self.subTest(original=original), patch.object(job.DownloadJob, "handle_url") as transport:
                with self.assertRaises(exception.AbortExtraction):
                    self.task.handle_url("https://node.hath.network/image.jpg",
                                         {"num": 1, "_original_sha1": digest})
                transport.assert_not_called()
                self.assertEqual(self.task.error, "original_unavailable")

    def test_resampled_bytes_never_pass_even_with_a_fullimg_route(self):
        self.path.write_bytes(b"\xff\xd8\xffresampled bytes")
        with patch.object(job.DownloadJob, "handle_url"), patch("favsync.eh_download.emit") as emit:
            with self.assertRaises(exception.AbortExtraction):
                self.task.handle_url("https://exhentai.org/fullimg.php",
                                     {"num": 1, "_original_sha1": DIGEST})
            emit.assert_not_called()
            self.assertEqual(self.task.error, "original_unavailable")

    def test_invalid_or_missing_media_never_reports_progress(self):
        for contents in (b"", b"<html>error</html>", None):
            if contents is None:
                self.path.unlink()
            else:
                self.path.write_bytes(contents)
            with self.subTest(contents=contents), patch.object(job.DownloadJob, "handle_url"), \
                    patch("favsync.eh_download.emit") as emit:
                with self.assertRaises(exception.AbortExtraction):
                    self.task.handle_url("https://exhentai.org/fullimg.php", {"num": 1})
                emit.assert_not_called()
                self.assertEqual(self.task.error, "incomplete_gallery")

    def test_pinned_job_resumes_completed_original_without_redownloading(self):
        config.clear()
        self.addCleanup(config.clear)
        config.set(("extractor", "exhentai"), "base-directory", self.temp.name)
        config.set(("extractor", "exhentai"), "directory", [])
        config.set(("extractor", "exhentai"), "filename", "{num:04}.{extension}")
        class FixtureExtractor(OriginalExtractor):
            def items(self):
                metadata = {"filecount": 1, "num": 1, "extension": "jpg", "_original_sha1": DIGEST}
                yield 2, "", metadata
                yield 3, "https://node.hath.network/native.jpg", metadata
        task = OriginalDownloadJob(FixtureExtractor.from_url(URL))
        task.out = output.NullOutput()
        task.download = Mock(side_effect=AssertionError("already completed page downloaded again"))
        with patch("favsync.eh_download.emit"):
            self.assertEqual(task.run(), 0)
        task.download.assert_not_called()

    def test_bundle_uses_one_pass_and_publishes_only_complete_zip(self):
        from favsync.adapters_ext import EhAdapter
        from favsync.config import load
        from favsync.store import Store
        config_path = Path(self.temp.name) / "config.toml"
        config_path.write_text('state_dir="state"\n[eh]\noutput_dir="' + self.temp.name + '"\n')
        cfg = load(config_path)
        cfg["storage"] = {"min_free_bytes": 0, "resume_free_bytes": 0}
        store = Store(cfg["state_dir"], initialize=True)
        self.addCleanup(store.close)
        adapter = EhAdapter(cfg, store)
        staging = Path(self.temp.name) / ".partial"
        staging.mkdir()
        metadata = {"filecount": 2, "title": "Fixture", "tags": ["artist:Fixture"]}
        def download(*args):
            for number in (1, 2):
                (staging / f"{number:04}.jpg").write_bytes(IMAGE)
            return metadata
        item = {"account": "fixture", "item_id": "123", "locator": json.dumps({"url": URL})}
        with patch.object(adapter, "_events", side_effect=AssertionError("full prescan")), \
                patch("favsync.eh_download.download_gallery", side_effect=download) as worker:
            artifacts = adapter.download_bundle(item, staging)
        worker.assert_called_once()
        with zipfile.ZipFile(artifacts[0]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ["0001.jpg", "0002.jpg", "ComicInfo.xml"])
        self.assertFalse(staging.exists())


if __name__ == "__main__":
    unittest.main()
