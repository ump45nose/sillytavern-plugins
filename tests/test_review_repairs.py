"""Bounded offline checks for the 2026-09-29 review repairs."""
import json
import multiprocessing
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import requests

from favsync.adapters_ext import XhsAdapter
from favsync.adapters_pixiv_wallabag import WallabagAdapter
from favsync.common import SyncError, process_lock
from favsync.config import load
from favsync.database import migrate
from favsync.engine import Engine
from favsync.media import valid_media
from favsync.sources import ScanResult
from favsync.store import Store


class ReviewRepairSmoke(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.toml"
        self.config.write_text('state_dir="state"\ndownload_dir="downloads"\n')
        self.cfg = load(self.config)
        self.cfg['storage'] = {'min_free_bytes': 0, 'resume_free_bytes': 0}

    def test_bundle_exception_does_not_skip_later_source_and_can_retry(self):
        class Broken:
            fail = True
            def scan(self, *_args, **_kwargs):
                return [{"id": "1", "text": "", "assets": [], "bundle": True, "locator": {}}], None
            def identity(self):
                return "fixture"
            def download_bundle(self, item, staging):
                if self.fail:
                    raise KeyError("unexpected library failure")
                (staging / 'fixture').write_bytes(b'complete')
                return [staging / 'fixture']
        class Later:
            calls = 0
            def sync_metadata(self, store, source, account):
                self.calls += 1
                store.update(source, account, scan_status='complete', error=None)
        broken, later = Broken(), Later()
        self.cfg['wallabag_entries']['enabled'] = True
        self.cfg['film_watchlist']['enabled'] = True
        engine = Engine(self.cfg, {'wallabag': broken, 'films': later})
        self.addCleanup(engine.store.close)
        with process_lock(self.cfg['state_dir'], name='scheduler'):
            self.assertFalse(engine.cycle())  # Idle scheduler does not hold the worker lock.
        self.assertEqual(later.calls, 1)
        self.assertEqual(engine.store.pending('wallabag_entries', 'personal')[0]['bundle_status'], 'failed')
        broken.fail = False
        self.assertTrue(engine.cycle())
        self.assertEqual(later.calls, 2)
        with process_lock(self.cfg['state_dir']):
            with self.assertRaisesRegex(SyncError, 'worker_already_running'):
                engine.cycle()

    def test_media_reads_header_only_and_malformed_epub_is_classified(self):
        path = self.root / 'large.mp4'
        with path.open('wb') as stream:
            stream.write(b'\x00\x00\x00\x18ftypisom')
            stream.truncate(128 * 1024 * 1024)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole file read')):
            self.assertTrue(valid_media(path))
        path = self.root / 'bad.epub'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('body.xhtml', '<p>missing mimetype</p>')
        with self.assertRaisesRegex(SyncError, 'epub_invalid'):
            WallabagAdapter._validate_epub(path, 1, 0)

    def test_seen_pending_xhs_gets_fresh_locator_without_renaming(self):
        store = Store(self.cfg['state_dir'], initialize=True)
        self.addCleanup(store.close)
        store.source('xhs_favorites', 'personal')
        record = {'id': 'note', 'text': '', 'assets': [], 'bundle': True,
                  'locator': {'url': 'old', 'author': 'Original', 'published': '2026-09-01',
                              'naming': {'group': 'Original', 'date': '2026-09-01'}}}
        store.ingest('xhs_favorites', 'personal', [record])
        store.save_xhs_detail('personal', 'note', {'stale': True})
        adapter = XhsAdapter(self.cfg, store)
        adapter.identity = lambda: 'fixture'
        adapter._pace = lambda: None
        adapter._env = lambda: {}
        with patch('favsync.adapters_ext._json_command', return_value={'ok': True, 'data': {
                'notes': [{'note_id': 'note', 'xsec_token': 'fresh', 'user': {'nickname': 'Renamed'}}],
                'has_more': True, 'cursor': 'next'}}):
            result = adapter.scan('xhs_favorites')
        self.assertEqual(result.reason, 'seen_boundary')
        self.assertEqual(len(result.records), 1)
        store.ingest('xhs_favorites', 'personal', result.records)
        item = store.pending('xhs_favorites', 'personal')[0]
        locator = json.loads(item['locator'])
        self.assertIn('xsec_token=fresh', locator['url'])
        self.assertEqual(locator['naming'], record['locator']['naming'])
        self.assertIsNone(store.xhs_detail('personal', 'note', 86400))
        self.assertFalse(ScanResult([], reason='page_limit').complete)
        self.assertFalse(ScanResult([], reason='request_budget').complete)

    def test_api_configuration_and_readonly_status_do_not_migrate(self):
        self.config.write_text(self.config.read_text() + '[pixiv]\nuid="invalid"\n'
                               '[pixiv_art_public]\nenabled=true\n')
        cfg = load(self.config, mode='film-api')
        migrate(cfg['state_dir'])
        with patch('favsync.database.migrate', side_effect=AssertionError('unexpected migration')):
            store = Store(cfg['state_dir'], readonly=True)
            try:
                store.status()
                self.assertEqual(store.db.total_changes, 0)
            finally:
                store.close()
        # Real HTTP handler, disposable database; no production film is added.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cfg['film_api']['port'] = sock.getsockname()[1]
        import os
        from favsync.film_api import serve
        with patch.dict(os.environ, FILM_API_TOKEN='fixture-only'):
            process = multiprocessing.Process(target=serve, args=(cfg,))
            process.start()
        session = requests.Session(); session.trust_env = False
        try:
            import time
            url = f"http://127.0.0.1:{cfg['film_api']['port']}"
            for _ in range(30):
                try:
                    session.get(url + '/health', timeout=.2).raise_for_status()
                    break
                except requests.RequestException:
                    time.sleep(.05)
            response = session.post(url + '/v1/films', timeout=2,
                                    headers={'Authorization': 'Bearer fixture-only'},
                                    json={'title': 'Fixture', 'release_year': 2026, 'release_date': '2026-10-01'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['release_date'], '2026-10-01')
        finally:
            session.close()
            process.terminate(); process.join(timeout=3)
