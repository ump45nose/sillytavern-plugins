"""来源退出后不再入库或加工；合成数据，不访问上游服务。"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import insert, select

from personal_data_hub.contracts import utcnow
from personal_data_hub.processing.query import ReadingQuery
from personal_data_hub.processing.repository import ProcessingRepository
from personal_data_hub.processing.schema import jobs, objects
from personal_data_hub.runner import configuration
from personal_data_hub.server import create_app
from personal_data_hub.storage import records, sources


class SourceCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        root = Path(self.temporary.name)
        (root / 'write').write_text('synthetic-writer')
        (root / 'read').write_text('synthetic-reader')
        self.config = {
            'database_url': 'sqlite:///' + str(root / 'hub.sqlite'),
            'asset_root': str(root / 'assets'),
            'hub_api_token_file': str(root / 'write'),
            'hub_viewer_token_file': str(root / 'read'),
            'sources': {name: {'adapter': adapter} for name, adapter in (
                ('sky', 'skysight'), ('plaud', 'plaud'),
                ('network', 'shellcrash'))},
        }
        self.app = create_app(self.config, webhook_only=True)
        self.client = TestClient(self.app)
        self.store = self.app.state.hub_store
        self.write = {'Authorization': 'Bearer synthetic-writer'}
        self.read = {'Authorization': 'Bearer synthetic-reader'}

    def tearDown(self):
        self.client.close()
        self.store.engine.dispose()
        self.temporary.cleanup()

    def test_removed_config_and_api_cannot_resume_sources(self):
        path = Path(self.temporary.name) / 'config.json'
        for adapter in ('memos', 'mem0', 'files', 'git', 'emby', 'navidrome', 'google', 'token', 'email', 'crm_pg', 'health', 'bills'):
            path.write_text(json.dumps(self.config | {'sources': {'removed': {'adapter': adapter}}}))
            with self.subTest(adapter=adapter), self.assertRaisesRegex(ValueError, 'unsupported_source_adapter'):
                configuration(path)
        response = self.client.post('/api/v1/ingest', headers=self.write,
            json={'batch_id': 'old', 'source': 'memos', 'records': []})
        self.assertEqual(response.status_code, 422)
        response = self.client.post('/api/v1/ingest', headers=self.write,
            json={'batch_id': 'disguised', 'source': 'sky', 'records': [
                {'external_id': 'memo', 'kind': 'memo', 'raw': {}}]})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.store.record_page()['total'], 0)

    def test_historical_data_survives_but_is_not_listed_rebuilt_or_claimed(self):
        now = utcnow()
        rid, oid = 'a' * 64, 'b' * 64
        with self.store.engine.begin() as c:
            c.execute(insert(sources).values(id='old-token', account='owner', adapter='token', deletion_support='explicit_only'))
            c.execute(insert(records).values(id=rid, source='old-token', external_id='old', kind='token_day',
                observed_at=now, timezone='Asia/Shanghai', hash='c' * 64, raw={'tokens': 10}, normalized={}, assets=[]))
            for identifier, processor in ((oid, 'metric-day-v1'), ('d' * 64, 'document-v1')):
                c.execute(insert(jobs).values(id=identifier, processor=processor, source='old-token', scope_key='old',
                    desired_generation=1, published_generation=0, profile_version=1, state='pending', attempts=0, updated_at=now))
            c.execute(insert(objects).values(id=oid, processor='metric-day-v1', source='old-token', account='owner',
                scope_key='old', type='metric_day', variant='usage_day', schema_version=1, revision=1, generation=1,
                timezone='Asia/Shanghai', title='历史用量', preview='', state='ready', details={}, warnings=[], coverage={}))
        self.assertIsNotNone(self.store.get_record(rid))
        self.assertEqual(self.store.list_records(), [])
        self.assertEqual(self.store.record_page()['total'], 0)
        self.assertEqual(self.store.kinds(), [])
        self.assertNotIn('old-token', {r['id'] for r in self.store.status()})
        reading = ReadingQuery(self.store)
        self.assertEqual(reading.page()['items'], [])
        self.assertIsNotNone(reading.detail(oid))
        repository = ProcessingRepository(self.store)
        self.assertFalse(repository.has_pending())
        self.assertIsNone(repository.claim())
        self.assertEqual(repository.rebuild(force=True)['scanned'], 0)
        self.assertEqual(repository.status()['source_coverage'], [])
        with self.store.engine.connect() as c:
            self.assertEqual(list(c.scalars(select(jobs.c.state))), ['pending', 'pending'])
        self.assertEqual(self.client.get('/api/v1/records/' + rid, headers=self.read).status_code, 200)

    def test_retained_pushes_and_display_boundaries(self):
        for source, kind, raw, normal in (
            ('sky', 'computer_summary', {}, {'content': '已有摘要', 'interval': '10min'}),
            ('plaud', 'recording', {'recording_id': 'audio'}, {'date': '2026-10-15', 'duration_ms': 1000}),
            ('network', 'traffic_hourly', {'bucket': '2026-10-15T12:00'}, {'upload_bytes': 10, 'download_bytes': 20}),
        ):
            response = self.client.post('/api/v1/ingest', headers=self.write, json={
                'batch_id': source, 'source': source, 'records': [{'external_id': 'one', 'kind': kind,
                    'raw': raw, 'normalized': normal, 'occurred_at': '2026-10-15T04:00:00Z'}]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['committed'])
        payload = {'timestamp': '2026-10-15T04:00:00Z', 'steps': [{'count': 10,
            'start_time': '2026-10-15T00:00:00+08:00', 'end_time': '2026-10-15T12:00:00+08:00'}]}
        self.assertEqual(self.client.post('/health/import', headers=self.write, json=payload).status_code, 404)
        bill = {'id': 1, 'state': 'Synced', 'type': 'Expend', 'time': 1792036800000,
                'money': 1, 'fee': 0, 'flag': 0, 'remark': 'synthetic'}
        self.assertEqual(self.client.post('/autoaccounting/v1/bills', headers=self.write, json=bill).status_code, 404)
        self.assertEqual(self.store.record_page()['total'], 3)
        self.assertEqual(self.client.get('/api/v1/records').status_code, 401)
        self.assertEqual(self.client.post('/api/v1/ingest', headers=self.read,
            json={'batch_id': 'readonly', 'source': 'sky'}).status_code, 401)
        for module in ('agenda', 'usage', 'mail', 'git', 'notes', 'health', 'finance'):
            response = self.client.get('/api/v1/dashboard', headers=self.read,
                params={'date': '2026-10-15', 'modules': module})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get('/api/v1/dashboard', headers=self.read,
            params={'date': '2026-10-15'}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
