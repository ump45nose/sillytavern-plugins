"""EH listing regressions; no account or network access is used."""
from contextlib import nullcontext
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from favsync.adapters_ext import EhAdapter
from favsync.common import SyncError, command
from favsync.config import load
from favsync.engine import Engine

try:
    from gallery_dl import config, exception, job
    from favsync.eh_favorites import FavoritesExtractor
except ImportError:
    FavoritesExtractor = None


FAVORITES = "https://exhentai.org/favorites.php"
GALLERY = "https://exhentai.org/g/123/0123456789/"


def page(next_url="", links=(GALLERY,)):
    return ('<script>nexturl="' + next_url + '";</script>'
            + "".join(f'<a href="{url}">gallery</a>' for url in links))


class EhAdapterTests(unittest.TestCase):
    def test_queue_events_are_collected_and_deduplicated(self):
        events = [[6, GALLERY, {"gallery_id": 123, "gallery_token": "0123456789"}]] * 2
        adapter = EhAdapter({})
        with patch.object(adapter, "_events", return_value=events):
            result = adapter.scan("eh_favorites")
        self.assertTrue(result.complete)
        self.assertEqual(result.records, [{"id": "123", "text": "", "assets": [],
                         "bundle": True, "locator": {"url": GALLERY}}])

    def test_listing_uses_checked_worker(self):
        adapter = EhAdapter({"command_timeout_seconds": 12})
        with patch.object(adapter, "config_file", return_value=nullcontext("config")), \
                patch("favsync.adapters_ext.command") as runner:
            runner.side_effect = lambda argv, timeout, output, **kw: output.write(b"[]")
            self.assertEqual(adapter._events(FAVORITES), [])
            self.assertEqual(runner.call_args.args[0][1:3], ["-m", "favsync.eh_favorites"])


@unittest.skipIf(FavoritesExtractor is None, "gallery extra is not installed")
class EhPaginationTests(unittest.TestCase):
    def extractor(self, pages):
        extractor = FavoritesExtractor.from_url(FAVORITES)
        extractor.search_url = FAVORITES
        extractor.login = Mock()
        extractor.request = Mock(side_effect=[SimpleNamespace(text=body) for body in pages])
        return extractor

    def test_two_pages_preserve_queue_metadata_without_opening_galleries(self):
        second = "https://exhentai.org/g/124/abcdef0123/"
        extractor = self.extractor([page(FAVORITES + "?next=124", (GALLERY, GALLERY)),
                                    page("", (second,))])
        events = list(extractor.items())
        self.assertEqual([event[0] for event in events], [6, 6])
        self.assertEqual([event[-1]["gallery_id"] for event in events], [123, 124])
        self.assertEqual(events[0][-1]["gallery_token"], "0123456789")
        self.assertEqual([call.args[0] for call in extractor.request.call_args_list],
                         [FAVORITES + "?page=0", FAVORITES + "?next=124"])

    def test_recognized_empty_and_legacy_last_pages_complete(self):
        for body in (page(links=()), "<p>No hits found</p>", '<td class="ptdd">&gt;</td>'):
            with self.subTest(body=body):
                self.assertEqual(list(self.extractor([body]).items()), [])

    def test_unrecognized_pages_stop_after_one_request(self):
        for body in ("", "<html>temporary error</html>", f'<a href="{GALLERY}">gallery</a>'):
            with self.subTest(body=body):
                extractor = self.extractor([body])
                with self.assertRaises(exception.ExtractionError):
                    list(extractor.items())
                self.assertEqual(extractor.request.call_count, 1)

    def test_repeated_and_reordered_pagination_cursors_stop(self):
        for pages, count in (([page(FAVORITES + "?page=0")], 1),
                             ([page(FAVORITES + "?next=1&a=2"),
                               page(FAVORITES + "?a=2&next=1")], 2)):
            extractor = self.extractor(pages)
            with self.assertRaises(exception.ExtractionError):
                list(extractor.items())
            self.assertEqual(extractor.request.call_count, count)

    def test_next_page_must_stay_on_the_authenticated_favorites_endpoint(self):
        for target in ("https://example.org/favorites.php?next=1",
                       "https://exhentai.org/g/123/0123456789/",
                       "http://exhentai.org/favorites.php?next=1"):
            with self.subTest(target=target):
                extractor = self.extractor([page(target)])
                with self.assertRaises(exception.ExtractionError):
                    list(extractor.items())
                self.assertEqual(extractor.request.call_count, 1)

    def test_html_escaped_relative_next_url_is_followed(self):
        extractor = self.extractor([page("?next=1&amp;favcat=2"), page()])
        list(extractor.items())
        self.assertEqual(extractor.request.call_args.args[0], FAVORITES + "?next=1&favcat=2")

    def data_job(self, pages):
        # Exercise the pinned DataJob, including its exit-zero terminal errors.
        config.clear()
        self.addCleanup(config.clear)
        extractor = self.extractor(pages)
        extractor.initialize = Mock()
        output = io.StringIO()
        self.assertEqual(job.DataJob(extractor, file=output).run(), 0)
        return json.loads(output.getvalue())

    def test_data_job_emits_queue_events(self):
        events = self.data_job([page()])
        self.assertEqual(events[0][0], 6)
        self.assertEqual(events[0][-1]["gallery_id"], 123)

    def test_real_worker_cli_preserves_strict_warning_policy(self):
        script = '''
from unittest.mock import patch
from types import SimpleNamespace
from favsync.eh_favorites import FavoritesExtractor, main
def login(self):
    if WARN:
        self.log.warning("fixture warning")
with patch.object(FavoritesExtractor, "login", login), patch.object(
        FavoritesExtractor, "request", return_value=SimpleNamespace(text=PAGE)):
    raise SystemExit(main())
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('state_dir="state"\n')
            cfg = load(path)
            Path(cfg["state_dir"]).mkdir()
            (Path(cfg["state_dir"]) / "eh-cookies.txt").write_text("# Netscape HTTP Cookie File\n")
            for warning in (False, True):
                def runner(argv, *args, **kwargs):
                    code = f"WARN={warning!r}\nPAGE={page()!r}\n" + script
                    return command([sys.executable, "-c", code, *argv[3:]], *args, **kwargs)
                with self.subTest(warning=warning), patch("favsync.adapters_ext.command", runner):
                    if warning:
                        with self.assertRaisesRegex(SyncError, "scan_incomplete"):
                            EhAdapter(cfg).scan("eh_favorites")
                    else:
                        result = EhAdapter(cfg).scan("eh_favorites")
                        self.assertEqual([record["id"] for record in result.records], ["123"])

    def test_pagination_failure_never_commits_a_partial_scan_or_baseline(self):
        events = self.data_job([page(FAVORITES + "?next=1"), "temporary error"])
        self.assertEqual([event[0] for event in events], [6, -1])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('state_dir="state"\n[eh_favorites]\nenabled=true\n')
            cfg = load(path)
            engine = Engine(cfg)
            self.addCleanup(engine.close)
            engine.store.source("eh_favorites", "personal")
            adapter = EhAdapter(cfg, engine.store)
            engine.adapters["eh"] = adapter

            def runner(argv, timeout, output, **kwargs):
                output.write(json.dumps(events).encode())

            for baseline in (None, 123):
                engine.store.update("eh_favorites", "personal", baseline_at=baseline)
                with self.subTest(baseline=baseline), \
                        patch.object(engine.guard, "check"), \
                        patch.object(adapter, "config_file", return_value=nullcontext("config")), \
                        patch("favsync.adapters_ext.command", side_effect=runner):
                    self.assertFalse(engine.cycle("eh_favorites"))
                state = engine.store.source("eh_favorites", "personal")
                self.assertEqual(state["baseline_at"], baseline)
                self.assertEqual(state["error"], "scan_incomplete")
                self.assertEqual(engine.store.db.execute("SELECT count(*) FROM seen").fetchone()[0], 0)
                self.assertEqual(engine.store.db.execute("SELECT count(*) FROM items").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
