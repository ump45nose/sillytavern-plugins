import json
from pathlib import Path
import tempfile
import unittest

from favsync.config import load
from favsync.engine import Engine
from favsync.layout import paths, platform_root
from favsync.migrate import relayout


class LayoutSmoke(unittest.TestCase):
    def test_requested_name_and_shared_platform_root(self):
        cfg = {'download_dir': '/root/downloads'}
        item = {'platform': 'telegram', 'account': 'personal', 'item_id': '116',
                'locator': json.dumps({'naming': {'tags': ['#yuna', '#申有娜'], 'group': '精妈俱乐部',
                                                'topic': 'kpop', 'date': '2026-09-18'}})}
        self.assertEqual(paths(cfg, item, {'number': 1, 'filename': '001.jpg'}),
                         Path('/root/downloads/Telegram/yuna申有娜_精妈俱乐部_kpop_2026-09-18_personal_116.jpg'))
        self.assertEqual(paths(cfg, item).suffix, '.md')
        self.assertEqual(platform_root(cfg, 'x'), Path('/root/downloads/Twitter'))
        self.assertEqual(platform_root(cfg, 'bilibili'), Path('/root/downloads/Bilibili'))
        self.assertNotEqual(paths(cfg, item, {'number': 1, 'filename': '001.jpg'}),
                            paths(cfg, item, {'number': 2, 'filename': '002.jpg'}))

    def test_migration_flat_collision_safe_and_restart_safe(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'config.toml').write_text('state_dir="state"\ndownload_dir="old"\n[telegram]\n')
            cfg = load(root / 'config.toml')
            engine = Engine(cfg)
            try:
                store = engine.store
                store.source('telegram', 'personal')
                records = [{'id': str(n), 'text': 'caption' if n == 1 else '',
                            'assets': [(1, '001.jpg')], 'locator': {'naming': {
                                'date': '2026-09-20', 'tags': ['#tag'], 'group': '../群/名称', 'topic': '话题'}}}
                           for n in (1, 2)]
                store.ingest('telegram', 'personal', records)
                for item in store.pending('telegram', 'personal'):
                    folder = root / 'old/telegram/personal' / item['item_id']
                    folder.mkdir(parents=True)
                    (folder / '001.jpg').write_bytes(b'fixture')
                    (folder / 'text.txt').write_text(item['body'])
                    store.asset_result(store.assets(item)[0], size=7)
                    store.text_done(item)
                result = relayout(engine)
                self.assertEqual(result['media_moved'], 2)
                self.assertEqual(result['nonempty_texts_archived'], 1)
                self.assertEqual(result['empty_texts_archived'], 1)
                self.assertEqual(len(list((root / 'old/Telegram').glob('*.jpg'))), 2)
                self.assertEqual(len(list((root / 'old/Telegram').glob('*.md'))), 1)
                self.assertEqual(relayout(engine)['media_moved'], 0)
                for item in store.db.execute('select * from items'):
                    self.assertEqual(paths(cfg, item).parent, root / 'old/Telegram')
                    self.assertIn('tag', paths(cfg, item, store.assets(item)[0]).name)
                    self.assertIn('2026-09-20', paths(cfg, item, store.assets(item)[0]).name)
            finally:
                engine.store.close()

    def test_saved_messages_do_not_create_new_text_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'c.toml').write_text('state_dir="state"\ndownload_dir="out"\n')
            cfg = load(root / 'c.toml');engine = Engine(cfg)
            try:
                engine.store.source('telegram', 'personal')
                engine.store.ingest('telegram', 'personal', [{'id': '1', 'text': 'body', 'locator': {}, 'assets': []}])
                self.assertTrue(engine.drain('telegram', 'personal', None))
                self.assertFalse(list((root / 'out').glob('**/*.txt')))
                engine.store.ingest('telegram', 'personal', [{'id': '2', 'text': '', 'locator': {}, 'assets': []},
                                                           {'id': '3', 'text': 'body', 'locator': {}, 'assets': []}])
                self.assertTrue(engine.drain('telegram', 'personal', None))
                self.assertFalse(list((root / 'out').glob('**/*.txt')))
                self.assertFalse((root/'out/Telegram/收藏.md').exists())
            finally:
                engine.store.close()
