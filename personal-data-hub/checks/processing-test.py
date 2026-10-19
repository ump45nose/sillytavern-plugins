"""Reading lifecycle regression. Synthetic data; optional PG runs in a disposable schema."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, insert, select, text, update

from personal_data_hub.contracts import Asset, Batch, Record, instant, utcnow
from personal_data_hub.storage import Store
from personal_data_hub.processing import activities
from personal_data_hub.processing.contracts import object_id
from personal_data_hub.processing.query import ContentChanged, ContentRemoved, ReadingQuery
from personal_data_hub.processing.repository import ProcessingRepository
from personal_data_hub.processing.schema import jobs, objects, blocks, inputs
from personal_data_hub.processing.worker import drain
from personal_data_hub.server import create_app


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.schema = None
        if os.environ.get('HUB_PROCESSING_TEST_POSTGRES') == '1':
            from personal_data_hub.runner import configuration
            config = configuration()
            self.admin = create_engine(config.get('database_url') or os.environ['HUB_DATABASE_URL'])
            if self.admin.dialect.name != 'postgresql': raise RuntimeError('postgres_required')
            self.schema = 'hub_processing_test_' + uuid4().hex
            with self.admin.begin() as c: c.execute(text('CREATE SCHEMA ' + self.schema))
            schema = self.schema
            # No source tables or locks from the production schema are used.
            class IsolatedStore(Store):
                @staticmethod
                def lock_id(key): return Store.lock_id(schema + ':' + key)
            # Construct with a search_path before Store creates its tables.
            with patch('personal_data_hub.storage.create_engine', side_effect=lambda *a, **kw:
                       create_engine(*a, **kw, connect_args={'options': '-csearch_path=' + schema})):
                self.store = IsolatedStore(self.admin.url, self.temp.name + '/assets')
        else:
            self.store = Store('sqlite:///' + self.temp.name + '/db', self.temp.name + '/assets')
        from personal_crm.archive import Archive
        Archive(engine=self.store.engine, asset_root=self.store.root)
        self.store.register('skysight-summaries', 'owner', 'skysight', 'explicit_only')
        self.repository = ProcessingRepository(self.store)
        self.query = ReadingQuery(self.store)

    def tearDown(self):
        self.store.engine.dispose()
        if self.schema:
            assert self.schema.startswith('hub_processing_test_') and len(self.schema) == 52
            with self.admin.begin() as c: c.execute(text('DROP SCHEMA ' + self.schema + ' CASCADE'))
            self.admin.dispose()
        self.temp.cleanup()

    def put(self, eid='one', body='#日报 2026-10-11\n\n## 状态\n今天的精力记录', kind='computer_summary', at='2026-10-11T00:00:00Z'):
        return self.store.ingest('skysight-summaries', Batch([Record(eid, kind, {'content': body}, {'content': body}, instant(at))]))

    def one(self): return self.query.page()['items'][0]

    def test_long_body_search_paging_and_evidence_are_lossless(self):
        body = '# 标题\n' + '字' * 7989 + '跨页词语' + '\n' + '末尾正文\n' * 60000
        self.put(body=body)
        result = drain(self.store)
        self.assertEqual(result['published'], 1)
        item = self.one()
        self.assertEqual(item['variant'], 'activity_summary')
        self.assertIsNone(item['summary'])
        self.assertEqual(len(self.query.page(query='跨页词语')['items']), 1)
        self.assertIn('跨页词语',self.query.page(query='跨页词语')['items'][0]['match']['excerpt'])
        self.assertGreater(self.query.page(query='末尾正文')['items'][0]['match']['ordinal'],0)
        self.assertEqual(len(self.query.page(query='末尾正文')['items']), 1)
        all_blocks, after = [], -1
        while True:
            page = self.query.block_page(item['id'], item['revision'], after, limit=50)
            self.assertLessEqual(len(json.dumps(page, ensure_ascii=False).encode()), 256 * 1024)
            all_blocks += page['blocks']
            if page['next_after'] is None: break
            after = page['next_after']
        self.assertEqual(''.join(b['text'] for b in all_blocks), body)
        self.assertEqual(len({b['key'] for b in all_blocks}), len(all_blocks))
        refs = self.query.evidence(item['id'])['inputs']
        self.assertTrue(refs[0]['current_matches'])
        self.assertNotIn('metadata', item)

    def test_duplicate_does_not_requeue_or_change_revision(self):
        self.put(); drain(self.store); item = self.one()
        self.assertEqual(self.put()['duplicates'], 1)
        self.assertEqual(drain(self.store)['claimed'], 0)
        self.assertEqual(self.one()['revision'], item['revision'])

    def test_update_fences_running_worker_and_old_body_pages(self):
        self.put(); drain(self.store); first = self.one()
        self.put(body='新的版本一'); job = self.repository.claim(); snapshot = self.repository.snapshot(job)
        content = activities.process(snapshot)
        self.put(body='新的版本二')
        self.assertEqual(self.one()['processing']['state'], 'stale')
        self.assertEqual(self.query.page(query='今天的精力')['items'][0]['processing']['state'], 'stale')
        old_page = self.query.block_page(first['id'], first['revision'])
        self.assertIn('今天的精力', ''.join(block['text'] for block in old_page['blocks']))
        self.assertEqual(old_page['processing']['state'], 'stale')
        self.assertFalse(self.query.evidence(first['id'], first['revision'])['inputs'][0]['current_matches'])
        self.assertFalse(self.repository.publish(job, snapshot, content))
        drain(self.store)
        self.assertEqual(self.query.block_page(first['id'], self.one()['revision'])['blocks'][0]['text'], '新的版本二')
        with self.assertRaises(ContentChanged): self.query.block_page(first['id'], first['revision'])

    def test_delete_withdraws_search_and_fences_inflight_worker(self):
        self.put(); drain(self.store); item = self.one()
        self.put(body='删除前新正文'); job = self.repository.claim(); snapshot = self.repository.snapshot(job)
        self.store.ingest('skysight-summaries', Batch(deletions=['one']))
        self.assertEqual(self.query.page(query='精力')['items'], [])
        self.assertIsNone(self.query.detail(item['id']))
        with self.assertRaises(ContentRemoved): self.query.block_page(item['id'], item['revision'])
        self.assertFalse(self.repository.publish(job, snapshot, activities.process(snapshot)))
        drain(self.store)
        self.assertEqual(self.query.page()['items'], [])
        self.assertEqual(self.put()['tombstoned'], 1)
        self.assertEqual(self.query.page()['items'], [])

    def test_rollback_keeps_queue_in_same_source_transaction(self):
        with self.assertRaises(RuntimeError), self.store.engine.begin() as c:
            self.store.ingest('skysight-summaries', Batch([Record('rollback','computer_summary',{'content':'不应存在'})]), connection=c)
            raise RuntimeError('rollback')
        self.assertEqual(self.query.page()['items'], [])
        self.assertEqual(drain(self.store)['claimed'], 0)

    def test_failure_is_visible_and_edit_recovers(self):
        self.store.ingest('skysight-summaries', Batch([Record('one','computer_summary',{'wrong':'missing body'})]))
        self.assertEqual(drain(self.store)['failed'], 1)
        self.assertEqual(self.one()['processing']['state'], 'failed')
        self.assertEqual(self.repository.status()['errors'][0]['error_code'], 'KeyError')
        self.put(body='恢复后的原文')
        self.assertEqual(drain(self.store)['published'], 1)
        self.assertEqual(self.one()['processing']['state'], 'ready')

    def test_expired_lease_cannot_publish_over_new_claim(self):
        self.put(); old = self.repository.claim(); rows = self.repository.snapshot(old)
        with self.store.engine.begin() as c:
            c.execute(update(jobs).where(jobs.c.id == old['id']).values(lease_until=utcnow()-timedelta(seconds=1)))
        new = self.repository.claim()
        self.assertNotEqual(old['lease_token'], new['lease_token'])
        self.assertFalse(self.repository.publish(old, rows, activities.process(rows)))
        self.assertTrue(self.repository.publish(new, rows, activities.process(rows)))


    def test_backfill_is_stable_idempotent_and_does_not_rewind_updates(self):
        from personal_data_hub.storage import records
        self.put('a'); self.put('b'); self.put('c')
        # Simulate archives predating the processing hook, without editing source facts.
        with self.store.engine.begin() as c:
            c.execute(__import__('sqlalchemy').delete(blocks)); c.execute(__import__('sqlalchemy').delete(inputs))
            c.execute(__import__('sqlalchemy').delete(objects)); c.execute(__import__('sqlalchemy').delete(jobs))
        page = self.repository.rebuild(limit=1)
        self.assertEqual(page['enqueued'], 1)
        self.assertIsNotNone(page['next_after'])
        self.put('a',body='回填期间的新版本')
        after=page['next_after'];scanned=page['scanned']
        while after:
            page=self.repository.rebuild(after=after,limit=1);after=page['next_after'];scanned+=page['scanned']
        self.assertEqual(scanned,3)
        self.assertEqual(self.repository.rebuild()['enqueued'],0)
        drain(self.store)
        self.assertEqual(len(self.query.page(query='回填期间的新版本')['items']),1)
        self.assertEqual(self.repository.rebuild(force=True)['enqueued'],3)

    def test_backup_includes_processing_and_migration_is_idempotent(self):
        from personal_crm.storage.models import Base
        from personal_data_hub.processing.schema import migrate, versions
        from personal_data_hub.migration import backup
        Base.metadata.create_all(self.store.engine)
        self.put();drain(self.store);migrate(self.store);migrate(self.store)
        with self.store.engine.connect() as c:self.assertEqual(c.scalar(select(__import__('sqlalchemy').func.count()).select_from(versions)),3)
        destination=Path(self.temp.name)/'backup.jsonl';backup(self.store,destination)
        tables={json.loads(line).get('table') for line in destination.read_text().splitlines()}
        self.assertTrue({'hub_content_objects','hub_content_blocks','hub_content_inputs','hub_processing_jobs','hub_processing_schema'} <= tables)

    def test_upgrade_of_early_m1_tables_adds_columns_and_rebuilds_only_output(self):
        from personal_data_hub.processing.schema import migrate, versions
        from personal_data_hub.storage import records
        self.put();drain(self.store)
        with self.store.engine.begin() as c:
            original=c.scalar(select(records.c.hash))
            c.execute(text('ALTER TABLE hub_content_objects DROP COLUMN business_date'))
            c.execute(text('ALTER TABLE hub_content_blocks DROP COLUMN search_text'))
            c.execute(__import__('sqlalchemy').delete(versions).where(versions.c.version==2))
        migrate(self.store)
        self.assertEqual(self.one()['processing']['state'],'stale')
        self.assertEqual(drain(self.store)['published'],1)
        self.assertIsNone(self.one()['business_date'])
        with self.store.engine.connect() as c:self.assertEqual(c.scalar(select(records.c.hash)),original)


    def test_keyset_filters_and_null_times(self):
        for eid,at in [('a','2026-10-11T00:00:00Z'),('b','2026-10-11T00:00:00Z'),('c',None)]:self.put(eid=eid,at=at)
        drain(self.store);ids=[];cursor=None
        while True:
            page=self.query.page(limit=1,cursor=cursor)
            ids+= [i['id'] for i in page['items']]
            if not page['next_cursor']:break
            cursor=page['next_cursor']
        self.assertEqual(len(ids),3);self.assertEqual(len(set(ids)),3)
        cursor=self.query.page(limit=1)['next_cursor']
        with self.assertRaises(ValueError):self.query.page(cursor=cursor,query='新条件')
        self.assertEqual(self.query.detail(ids[-1])['occurred_at'],None)

    def test_internal_api_auth_revision_and_bounds(self):
        cfg={'sources':{},'hub_api_token_file':self.temp.name+'/writer','hub_viewer_token_file':self.temp.name+'/viewer'}
        Path(cfg['hub_api_token_file']).write_text('writer');Path(cfg['hub_viewer_token_file']).write_text('viewer')
        with patch('personal_data_hub.server.store_from',return_value=self.store):app=create_app(cfg,webhook_only=True)
        client=TestClient(app);headers={'Authorization':'Bearer viewer'}
        self.put();drain(self.store);item=self.one()
        self.assertEqual(client.get('/api/v1/contents').status_code,401)
        self.assertEqual(client.get('/api/v1/processing/status',headers=headers).status_code,200)
        self.assertEqual(client.get('/api/v1/contents',params={'limit':51},headers=headers).status_code,422)
        self.assertEqual(client.get('/api/v1/contents',params={'cursor':'!'*100},headers=headers).status_code,422)
        path='/api/v1/contents/'+item['id']+'/blocks'
        self.assertEqual(client.get(path,params={'revision':99},headers=headers).status_code,409)
        self.store.ingest('skysight-summaries',Batch(deletions=['one']))
        self.assertEqual(client.get(path,params={'revision':1},headers=headers).status_code,404)

    def test_postgres_concurrent_publication_and_delete(self):
        if not self.schema:self.skipTest('run with HUB_PROCESSING_TEST_POSTGRES=1')
        self.put();drain(self.store);identifier=self.one()['id']
        self.put(body='并发中的正文');job=self.repository.claim();rows=self.repository.snapshot(job)
        barrier=threading.Barrier(2)
        def publish():barrier.wait();return self.repository.publish(job,rows,activities.process(rows))
        def remove():barrier.wait();return self.store.ingest('skysight-summaries',Batch(deletions=['one']))
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(publish);b=pool.submit(remove);a.result(timeout=15);b.result(timeout=15)
        self.assertIsNone(self.query.detail(identifier));self.assertEqual(self.query.page(query='并发')['items'],[])

    def test_concurrent_workers_claim_distinct_jobs(self):
        self.put('first');self.put('second')
        barrier=threading.Barrier(2)
        def claim():barrier.wait();return self.repository.claim()
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(claim);b=pool.submit(claim)
            left,right=a.result(timeout=15),b.result(timeout=15)
        self.assertIsNotNone(left);self.assertIsNotNone(right);self.assertNotEqual(left['id'],right['id'])

    def test_processing_lane_does_not_consume_source_slots(self):
        from personal_data_hub import scheduler
        clock=[0];started=[]
        class Process:
            def __init__(self,args,**kwargs):
                self.command=next(a for a in args if a in ('collect','rebuild-content','process-pending'));self.source=args[-1];self.pid=100+len(started);self.stopped=False
                started.append((clock[0],self.command,self.source))
            def poll(self):return 1 if self.stopped else (None if self.source=='slow' else 0)
        def sleep(_):
            clock[0]+=5
            if clock[0]>25:raise KeyboardInterrupt
        with patch.object(scheduler.subprocess,'Popen',Process),patch.object(scheduler.time,'monotonic',side_effect=lambda:clock[0]),patch.object(scheduler.time,'sleep',side_effect=sleep),patch.object(scheduler,'stop_worker',side_effect=lambda p:setattr(p,'stopped',True)),patch.object(scheduler,'interrupted'),patch.object(ProcessingRepository,'has_pending',side_effect=[True,False,False,False]):
            scheduler.serve(self.store,{'collector_workers':1,'processing_backfill_on_start':True,'processing_interval_seconds':10,'sources':{'slow':{'interval_seconds':900}}})
        self.assertIn((0,'collect','slow'),started)
        self.assertEqual(sum(command=='rebuild-content' for _,command,_ in started),1)
        self.assertEqual(sum(command=='process-pending' for _,command,_ in started),1)


if __name__=='__main__': unittest.main()
