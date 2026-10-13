"""Final checks for avoiding no-op database work; synthetic data only."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import delete, event, insert, select

from personal_data_hub import runner
from personal_data_hub.contracts import Batch, Record, instant, utcnow
from personal_data_hub.processing.registry import COLLECTION_PROFILES
from personal_data_hub.processing.repository import ProcessingRepository
from personal_data_hub.processing.schema import members
from personal_data_hub.storage import checkpoints, records, runs


class RuntimePerformanceTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('processing_fixture', Path(__file__).with_name('processing-test.py'))
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        self.case = fixture.ProcessingTests()
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_periodic_duplicates_advance_source_check_without_rewriting_content(self):
        store = self.case.store
        body = '相同笔记不反复更新归档与展示索引'
        self.case.put(body=body)
        with store.engine.connect() as c:
            before = c.scalar(select(records.c.observed_at))
        statements = []
        event.listen(store.engine, 'before_cursor_execute', lambda c, cur, sql, params, ctx, many: statements.append(sql))
        adapter = Mock()
        adapter.collect.return_value = [Batch([Record('one', 'memo', {'content': body}, {'content': body},
                                                       instant('2026-10-11T00:00:00Z'))], next_cursor={'checked': 1})]
        with patch.object(runner, 'adapter', return_value=adapter):
            result = runner.run(store, 'memos', {'adapter': 'memos'})
        self.assertEqual(result['duplicates'], 1)
        self.assertEqual(result['changed'], 0)
        self.assertFalse(any(sql.startswith(('UPDATE hub_records ', 'UPDATE hub_display_index ')) for sql in statements))
        self.assertEqual(store.cursor('memos'), {'checked': 1})
        with store.engine.connect() as c:
            self.assertEqual(c.scalar(select(records.c.observed_at)), before)
            self.assertEqual(c.scalar(select(runs.c.status)), 'ok')
        # Explicit observations and pushes retain their existing freshness contract.
        statements.clear()
        store.ingest('memos', adapter.collect.return_value[0])
        self.assertTrue(any(sql.startswith('UPDATE hub_records ') for sql in statements))

    def test_resumed_backfill_reads_bodies_only_for_missing_routes(self):
        store = self.case.store
        self.case.put('one', body='已经路由的正文')
        self.case.put('two', body='待补齐的正文')
        with store.engine.begin() as c:
            c.execute(delete(members).where(members.c.record_id == store.identity('memos', 'two')))
            c.execute(insert(checkpoints).values(source='processing:reading-backfill', updated_at=utcnow(), value={
                'profiles': {name: profile.PROFILE_VERSION for name, profile in COLLECTION_PROFILES.items()},
                'after': None, 'complete': False}))
        statements = []
        event.listen(store.engine, 'before_cursor_execute', lambda c, cur, sql, params, ctx, many: statements.append((sql, params)))
        result = ProcessingRepository(store).rebuild(limit=50, background_page=True)
        self.assertEqual(result['scanned'], 2)
        self.assertEqual(result['enqueued'], 1)
        self.assertTrue(result['complete'])
        body_reads = [(sql, params) for sql, params in statements if 'hub_records.raw' in sql]
        self.assertEqual(len(body_reads), 1)
        self.assertIn(store.identity('memos', 'two'), str(body_reads[0][1]))
        self.assertNotIn(store.identity('memos', 'one'), str(body_reads[0][1]))
        self.assertEqual(store.cursor('processing:reading-backfill')['complete'], True)


if __name__ == '__main__':
    unittest.main()
