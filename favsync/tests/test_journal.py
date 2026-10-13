import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote

from favsync.config import load
from favsync.common import SyncError
from favsync.engine import Engine
from favsync.legacy_journal import append_entry, journal_path
from favsync.layout import paths
from favsync.adapters import parse_x


class JournalSmoke(unittest.TestCase):
    def test_legacy_journal_requires_explicit_maintenance_and_recovers_torn_append(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'config.toml').write_text('state_dir="state"\ndownload_dir="downloads"\n')
            cfg = load(root/'config.toml'); cfg['storage'] = {'min_free_bytes': 0, 'resume_free_bytes': 0}; e = Engine(cfg)
            class Adapter:
                fail = True
                def download(self, item, asset, staging):
                    if self.fail: raise SyncError('fixture_failure')
                    p = staging/asset['filename'];p.write_bytes(b'fixture');return p
            adapter=Adapter()
            try:
                e.store.source('telegram','personal')
                r={'id':'116','text':'正文\n<!-- favsync:x:personal:9:end -->','assets':[(1,'001.jpg')],
                   'locator':{'naming':{'tags':['#标签'],'group':'群','topic':'话题','date':'2026-09-18'}}}
                e.store.ingest('telegram','personal',[r])
                self.assertFalse(e.drain('telegram','personal',adapter))
                target=journal_path(cfg,'telegram');self.assertFalse(target.exists())
                adapter.fail=False;e.attempted.clear();self.assertTrue(e.drain('telegram','personal',adapter))
                self.assertFalse(target.exists())  # Normal downloads no longer append the legacy journal.
                item = e.store.db.execute('SELECT * FROM items WHERE item_id=?', ('116',)).fetchone()
                append_entry(cfg, item, e.store.assets(item))
                content=target.read_text();self.assertIn('![图片 1]',content);self.assertIn('&lt;!--',content)
                self.assertIn('标签_群_话题_2026-09-18_personal_116.jpg',unquote(content))
                self.assertFalse(list(target.parent.glob('*.txt')))
                # File already committed but database update was lost.
                with e.store.db:e.store.db.execute('update items set text_done=0')
                self.assertTrue(e.drain('telegram','personal',adapter))
                self.assertFalse(append_entry(cfg, item, e.store.assets(item)))
                self.assertEqual(content,target.read_text())
                r2={'id':'117','text':'第二条','assets':[],'locator':{}}
                e.store.ingest('telegram','personal',[r2])
                with target.open('a') as f:f.write('<!-- favsync:telegram:personal:117:start -->\n- torn')
                self.assertTrue(e.drain('telegram','personal',adapter))
                second = e.store.db.execute('SELECT * FROM items WHERE item_id=?', ('117',)).fetchone()
                append_entry(cfg, second, [])
                self.assertNotIn('torn',target.read_text());self.assertEqual(target.read_text().count(':end -->'),2)
                self.assertEqual(target.read_text().count('\n- **'),2)
            finally:e.store.close()

    def test_x_flat_names_use_post_author_and_post_date(self):
        meta={'tweet_id':123,'date':'2026-09-18 16:30:00+00:00','author':{'nick':'作者','name':'author'},
              'user':{'nick':'登录者'},'content':'#标签 正文','hashtags':['标签'],'count':1,'num':1,'extension':'jpg'}
        r=parse_x([[2,meta],[3,'https://example.invalid/image',meta]])[0]
        item={'platform':'x','account':'personal','item_id':'123','locator':json.dumps(r['locator'])}
        p=paths({'download_dir':'/downloads'},item,{'number':1,'filename':'001.jpg'})
        self.assertEqual(str(p),'/downloads/Twitter/标签_作者_2026-09-19_personal_123.jpg')
