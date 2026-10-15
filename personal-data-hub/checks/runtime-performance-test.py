"""Final checks for avoiding no-op database work; synthetic data only."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import delete, event, insert, select, text

from personal_data_hub import runner, scheduler
from personal_data_hub.contracts import Batch, Record, instant, utcnow
from personal_data_hub.processing.registry import COLLECTION_PROFILES, PROFILES
from personal_data_hub.processing.repository import ProcessingRepository
from personal_data_hub.processing.schema import jobs, members, objects
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
        adapter.collect.return_value = [Batch([Record('one', 'computer_summary', {'content': body}, {'content': body},
                                                       instant('2026-10-11T00:00:00Z'))], next_cursor={'checked': 1})]
        with patch.object(runner, 'adapter', return_value=adapter):
            result = runner.run(store, 'skysight-summaries', {'adapter': 'skysight'})
        self.assertEqual(result['duplicates'], 1)
        self.assertEqual(result['changed'], 0)
        self.assertFalse(any(sql.startswith(('UPDATE hub_records ', 'UPDATE hub_display_index ')) for sql in statements))
        self.assertEqual(store.cursor('skysight-summaries'), {'checked': 1})
        with store.engine.connect() as c:
            self.assertEqual(c.scalar(select(records.c.observed_at)), before)
            self.assertEqual(c.scalar(select(runs.c.status)), 'ok')
        # Explicit observations and pushes retain their existing freshness contract.
        statements.clear()
        store.ingest('skysight-summaries', adapter.collect.return_value[0])
        self.assertTrue(any(sql.startswith('UPDATE hub_records ') for sql in statements))

    def test_resumed_backfill_reads_bodies_only_for_missing_routes(self):
        store = self.case.store
        self.case.put('one', body='已经路由的正文')
        self.case.put('two', body='待补齐的正文')
        with store.engine.begin() as c:
            c.execute(delete(members).where(members.c.record_id == store.identity('skysight-summaries', 'two')))
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
        self.assertIn(store.identity('skysight-summaries', 'two'), str(body_reads[0][1]))
        self.assertNotIn(store.identity('skysight-summaries', 'one'), str(body_reads[0][1]))
        self.assertEqual(store.cursor('processing:reading-backfill')['complete'], True)

    def test_idle_scheduler_sleeps_between_batches_and_preserves_source_intervals(self):
        clock, spawned, queue_checks = [0], [], []

        class Process:
            def __init__(self, args, **kwargs):
                self.pid = 100 + len(spawned)
                spawned.append(args)

            def poll(self):
                return 0

        def has_pending(repository):
            queue_checks.append(clock[0])
            return False

        def sleep(_):
            clock[0] += 30
            if clock[0] >= 180:
                raise KeyboardInterrupt

        with patch.object(scheduler.subprocess, 'Popen', Process), \
             patch.object(scheduler.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(scheduler.time, 'sleep', side_effect=sleep), \
             patch.object(scheduler, 'interrupted'), \
             patch.object(ProcessingRepository, 'has_pending', has_pending):
            scheduler.serve(None, {'sources': {'ordinary': {}, 'frequent': {'interval_seconds': 60}}})
        self.assertEqual(len(queue_checks), 1)
        self.assertEqual(sum(args[-1] == 'ordinary' for args in spawned), 1)
        self.assertGreater(sum(args[-1] == 'frequent' for args in spawned), 1)
        self.assertTrue(all('--skip-schema-init' in args for args in spawned))

    def test_backlog_does_not_bypass_interval_after_success_or_failure(self):
        for exit_code in (0, 1):
            with self.subTest(exit_code=exit_code):
                clock, spawned = [0], []

                class Process:
                    def __init__(self, args, **kwargs):
                        self.pid = 100 + len(spawned)
                        spawned.append((clock[0], args))

                    def poll(self): return exit_code

                def sleep(_):
                    clock[0] += 10
                    if clock[0] >= 180: raise KeyboardInterrupt

                with patch.object(scheduler.subprocess, 'Popen', Process), \
                     patch.object(scheduler.time, 'monotonic', side_effect=lambda: clock[0]), \
                     patch.object(scheduler.time, 'sleep', side_effect=sleep), \
                     patch.object(scheduler, 'stop_worker'), \
                     patch.object(ProcessingRepository, 'has_pending', return_value=True):
                    scheduler.serve(None, {'sources': {}, 'processing_interval_seconds': 120})
                self.assertEqual(len(spawned), 2)
                self.assertGreaterEqual(spawned[1][0] - spawned[0][0], 120)
                self.assertTrue(all(args[-4:] == ['--limit', '1000', '--max-seconds', '300'] for _, args in spawned))

    def test_publication_does_not_take_global_archive_lock(self):
        store = self.case.store
        if store.engine.dialect.name != 'postgresql': self.skipTest('PostgreSQL publication locks')
        self.case.put(body='发布不阻塞无关来源')
        repository = self.case.repository
        job = repository.claim(lease_seconds=180)
        rows = repository.snapshot(job)
        with store.writer_lock():
            self.assertTrue(repository.publish(job, rows, PROFILES[job['processor']].process(rows)))
        with store.engine.connect() as c:
            self.assertEqual(c.scalar(text("SELECT current_setting('statement_timeout')")), '0')


if __name__ == '__main__':
    unittest.main()
