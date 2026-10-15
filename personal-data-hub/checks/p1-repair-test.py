"""Final P1 checks, synthetic records in an isolated database/schema."""
import importlib.util
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import unittest
from unittest.mock import patch

from sqlalchemy import delete, event, select, text, update
from personal_data_hub.contracts import Asset, Batch, Record, utcnow
from personal_data_hub.crm_archive import reconcile
from personal_data_hub.processing.registry import PROFILES
from personal_data_hub.processing.schema import blocks, jobs
from personal_data_hub.processing.worker import drain
from personal_data_hub.storage import records, tombstones
from personal_crm.storage import CrmRepository
from personal_crm.storage.models import Person, Interaction


class P1Tests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('processing-test.py'))
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.case = module.ProcessingTests(); self.case.setUp()
        self.store = self.case.store

    def tearDown(self): self.case.tearDown()

    def crm(self):
        self.store.register('crm', 'owner', 'crm_pg', 'explicit_only')
        if self.store.engine.dialect.name == 'sqlite':
            with self.store.engine.connect() as c: c.execute(text('PRAGMA foreign_keys=ON'))
        with patch('personal_crm.storage.repository.create_engine', return_value=self.store.engine):
            return CrmRepository(str(self.store.engine.url), hub_store=self.store)

    def archived(self, eid): return self.store.get_record(self.store.identity('crm', eid))

    def test_batch_processes_multiple_jobs_and_obeys_time_budget(self):
        for i in range(4): self.case.put(str(i), body='待处理正文')
        with patch('personal_data_hub.processing.worker.time.monotonic', side_effect=[0, 0, 1, 6]):
            result = drain(self.store, limit=1000, max_seconds=5)
        self.assertEqual(result['published'], 2)
        self.assertEqual(drain(self.store, limit=1000, max_seconds=5)['published'], 2)

    def test_asset_preparation_runs_before_writer_lock_and_leaves_no_temporary_files(self):
        preparing = [False]
        original_prepare, original_lock = self.store.prepare_asset, self.store.writer_lock
        @contextmanager
        def prepare(asset):
            preparing[0] = True
            with original_prepare(asset) as value:
                preparing[0] = False
                yield value
        @contextmanager
        def lock(connection=None):
            self.assertFalse(preparing[0])
            with original_lock(connection): yield
        with patch.object(self.store, 'prepare_asset', prepare), patch.object(self.store, 'writer_lock', lock):
            self.store.ingest('skysight-summaries', Batch([Record('asset', 'computer_summary', {'content': '附件'}, {'content': '附件'}, assets=[Asset('file', content=b'example')])]))
        row = self.store.get_record(self.store.identity('skysight-summaries', 'asset'))
        self.assertEqual(self.store.asset_path(row['assets'][0]['id']).read_bytes(), b'example')
        self.assertEqual(list(self.store.root.glob('.asset-*')), [])

    def test_input_edit_yields_without_losing_job_or_deadlocking(self):
        if not self.case.schema: self.skipTest('PostgreSQL locks')
        self.case.put(); repo = self.case.repository
        job = repo.claim(); rows = repo.snapshot(job); content = PROFILES[job['processor']].process(rows)
        with self.store.engine.connect() as c:
            tx = c.begin()
            c.execute(update(records).where(records.c.id == rows[0]['id']).values(hash='editing'))
            self.assertFalse(repo.publish(job, rows, content))
            tx.rollback()
        self.assertIsNone(repo.claim())
        with self.store.engine.begin() as c:
            c.execute(update(jobs).where(jobs.c.id == job['id']).values(retry_at=utcnow()))
        job = repo.claim()
        self.assertTrue(repo.publish(job, rows, content))

    def test_unchanged_blocks_do_not_rewrite_search_index(self):
        self.case.put(); drain(self.store)
        repo = self.case.repository
        with self.store.engine.begin() as c:
            row = c.execute(select(records)).mappings().one()
            repo.changed(c, row)
        statements = []
        def capture(c, cur, sql, params, ctx, many): statements.append(sql)
        event.listen(self.store.engine, 'before_cursor_execute', capture)
        try: self.assertEqual(drain(self.store)['published'], 1)
        finally: event.remove(self.store.engine, 'before_cursor_execute', capture)
        self.assertFalse(any(sql.startswith(('DELETE FROM hub_content_blocks', 'INSERT INTO hub_content_blocks', 'UPDATE hub_content_blocks')) for sql in statements))

    def test_crm_all_entity_changes_and_rollback_are_mirrored(self):
        crm = self.crm()
        person = crm.create_person(display_name='甲')
        crm.upsert_person(person.id, display_name='乙')
        self.assertEqual(self.archived('people:' + person.id)['raw']['display_name'], '乙')
        interaction, _, _ = crm.record_interaction(person_id=person.id, occurred_at=utcnow(), interaction_type='manual_note', channel='manual', direction='mutual', summary='记录', source_type='manual', source_event_key='event-one')
        fact, _ = crm.record_fact(person_id=person.id, fact_type='other', content='已确认事实', observed_at=utcnow(), source_interaction_id=interaction.id)
        reminder = crm.create_reminder(person_id=person.id, reminder_type='custom', due_at=utcnow(), reason='提醒')
        crm.update_reminder(reminder.id, reason='更正提醒')
        self.assertEqual(self.archived('reminders:' + reminder.id)['raw']['reason'], '更正提醒')
        self.assertIsNotNone(self.archived('facts:' + fact.id))
        with self.assertRaises(RuntimeError):
            with crm.transaction() as session:
                p = session.get(Person, person.id); p.display_name='回滚'; session.flush()
                raise RuntimeError('abort')
        self.assertEqual(self.archived('people:' + person.id)['raw']['display_name'], '乙')
        # Database ON DELETE SET NULL must also be mirrored.
        with crm.transaction() as session: session.delete(session.get(Interaction, interaction.id))
        self.assertIsNone(self.archived('facts:' + fact.id)['raw']['source_interaction_id'])
        with self.store.engine.connect() as c:
            self.assertTrue(self.store.crm_event_deleted(c, 'manual', 'event-one'))
        crm.delete_person(person.id)
        for eid in ('people:' + person.id, 'facts:' + fact.id, 'reminders:' + reminder.id):
            self.assertIsNone(self.archived(eid))

    def test_crm_merge_keeps_moved_records_and_reconciliation_is_idempotent(self):
        crm = self.crm()
        a = crm.create_person(display_name='甲'); b = crm.create_person(display_name='乙')
        interaction, _, _ = crm.record_interaction(person_id=a.id, occurred_at=utcnow(), interaction_type='manual_note', channel='manual', direction='mutual', summary='记录', source_type='manual')
        crm.merge_people(a.id, b.id)
        self.assertIsNone(self.archived('people:' + a.id))
        self.assertEqual(self.archived('interactions:' + interaction.id)['raw']['person_id'], b.id)
        self.assertEqual(reconcile(self.store, batch_size=1)['changed'], 0)
        # Repair rows created by a legacy/direct SQL writer, and missing natives.
        with self.store.engine.begin() as c:
            c.execute(Person.__table__.insert().values(id='legacy', display_name='旧写入'))
        self.assertEqual(reconcile(self.store, batch_size=1)['changed'], 1)
        with self.store.engine.begin() as c: c.execute(delete(Person).where(Person.id == 'legacy'))
        self.assertEqual(reconcile(self.store, batch_size=1)['deleted'], 1)

    def test_wechat_replay_media_and_client_watermark(self):
        crm = self.crm(); at = utcnow().replace(microsecond=0)
        item = dict(person_name='联系人', wxid='wxid-p1', occurred_at=at,
                    interaction_type='message', channel='wechat', direction='inbound',
                    summary='消息内容：原文', source_event_key='wechat-one',
                    message=dict(account_namespace='owner', conversation_id='wxid-p1',
                                 conversation_type='direct', record={'content': '原文', 'ts': at.timestamp()}))
        self.assertEqual(crm.import_wechat_batch('chatlog', [item], [], synced_through=at), (1, 0))
        interaction = crm.list_interactions()[0]
        self.assertEqual(crm.attach_wechat_media('wechat-one', None, Asset('voice', content=b'audio'))['status'], 'attached')
        self.assertEqual(crm.import_wechat_batch('chatlog', [item], [], synced_through=at), (0, 1))
        archived = self.archived('interactions:' + interaction.id)
        self.assertEqual(len(archived['assets']), 1)
        self.assertEqual(archived['raw']['message']['record']['content'], '原文')
        self.assertEqual(reconcile(self.store, batch_size=1)['changed'], 0)
        crm.delete_person(interaction.person_id)
        self.assertEqual(crm.import_wechat_batch('chatlog', [item], []), (0, 1))
        self.assertIsNone(self.archived('interactions:' + interaction.id))

    def test_crm_reconcile_source_lock_does_not_block_live_writes(self):
        if not self.case.schema: self.skipTest('PostgreSQL locks')
        crm = self.crm()
        with self.store.lock('source:crm'), ThreadPoolExecutor(1) as pool:
            person = pool.submit(crm.create_person, display_name='实时写入').result(timeout=5)
        self.assertIsNotNone(self.archived('people:' + person.id))


if __name__ == '__main__': unittest.main()
