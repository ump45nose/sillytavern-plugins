"""Validate direct service pagination/failure and device-scoped published archives."""
from datetime import datetime, timezone
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from review.domain import TimeWindow
from review.sources.crm_activity import CrmActivitySource
from review.sources.skysight import SkysightSummarySource


class DirectInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.window = TimeWindow(datetime(2026, 10, 19, tzinfo=timezone.utc),
                                 datetime(2026, 10, 19, 21, 30, tzinfo=timezone.utc))

    def serve_crm(self, failed=False):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_GET(self):
                path = urlsplit(self.path); query = parse_qs(path.query)
                requests.append((path.path, query, self.headers.get('Authorization')))
                if failed:
                    self.send_error(503); return
                row = {'id':'one', 'date':'2026-10-19', 'started_at':'2026-10-19T10:00:00+00:00',
                       'updated_at':'2026-10-19T10:10:00+00:00', 'person_ids':['p'], 'preview':'private text'}
                if path.path.endswith('/people'):
                    data = {'items':[{'id':'p','name':'测试联系人'}], 'next_cursor':None}
                elif 'cursor' in query:
                    data = {'items':[{**row, 'id':'two'}], 'next_cursor':None}
                else:
                    data = {'items':[row,{**row,'id':'late','started_at':'2026-10-19T22:00:00+00:00'}], 'next_cursor':'next'}
                self.send_response(200); self.send_header('Content-Type','application/json');self.end_headers()
                self.wfile.write(json.dumps(data).encode())
        server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread = Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        token = self.root/'read.token';token.write_text('test-read')
        return CrmActivitySource(f'http://127.0.0.1:{server.server_port}',token), requests

    def test_crm_paginates_and_excludes_after_cutoff_without_mirroring_text(self):
        source, requests = self.serve_crm()
        result = source.collect(self.window,None)
        self.assertEqual(result.evidence[0].payload['change_count'],2)
        self.assertNotIn('private text',str(result))
        self.assertEqual(len(requests),3)
        self.assertEqual(requests[0][1]['start'],['2026-10-19'])
        self.assertTrue(all(auth=='Bearer test-read' for _,_,auth in requests))

    def test_crm_unavailable_is_not_reported_as_zero_interactions(self):
        source,_ = self.serve_crm(failed=True)
        with self.assertRaises(HTTPError):source.collect(self.window,None)

    def test_skysight_uses_published_objects_and_keeps_other_device_detail(self):
        def publish(device, documents):
            base=self.root/'devices'/device;entries={}
            for name,body in documents.items():
                digest=sha256(body.encode()).hexdigest();p=base/'objects'/digest/name
                p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
                entries[name]={'name':name,'sha256':digest,'size':len(body)}
            (base/'manifest.json').write_text(json.dumps({'entries':entries}))
        six='2026-10-19T00-00-00-a-6h-memory-summary.md'
        detail='2026-10-19T00-10-00-b-10min-memory-summary.md'
        publish('a',{six:'## Memory summary\n完整摘要\n## Recording summary\n详细记录',detail:'重复细节'})
        publish('b',{detail:'另一台电脑的细节'})
        result=SkysightSummarySource(self.root).collect(self.window,None)
        self.assertEqual(len(result.evidence),2)
        text='\n'.join(row.payload['summary_markdown'] for row in result.evidence)
        self.assertIn('详细记录',text);self.assertIn('另一台电脑的细节',text);self.assertNotIn('重复细节',text)
        (self.root/'devices'/'a'/'manifest.json').unlink()
        # A staged object without a published manifest is never consumed.
        self.assertEqual(len(SkysightSummarySource(self.root).collect(self.window,None).evidence),1)
