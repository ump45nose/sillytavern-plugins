"""Regression checks for interruption recovery, retry and faithful JSONL."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import insert, select, event
from personal_data_hub import runner, scheduler
from personal_data_hub.storage import Store, runs, records
from personal_data_hub.collectors import FilesCollector
from personal_data_hub.contracts import Batch, Record, utcnow

class UnattendedTests(unittest.TestCase):
 def test_unicode_line_separators_are_json_text_and_invalid_files_revalidate(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'segment';p.mkdir();(p/'metadata.json').write_text(json.dumps({'startedAt':'2026-10-10T00:00:00Z','endedAt':'2026-10-10T00:10:00Z','eventCount':1}))
   original={'text':'before\u2028after\u0085end'}
   (p/'events.jsonl').write_text(json.dumps(original,ensure_ascii=False)+'\n')
   collector=FilesCollector({'adapter':'skysight','path':tmp,'patterns':['*/metadata.json']})
   first=list(collector.collect({}));cursor=first[-1].next_cursor
   self.assertEqual(first[0].records[0].normalized['events'],[original])
   cursor['segment_validator_version']=1;cursor['invalid_ids']=['segment/metadata.json']
   healed=list(collector.collect(cursor))
   self.assertEqual(healed[0].records[0].kind,'computer_segment')
   self.assertEqual(healed[-1].next_cursor['invalid_ids'],[])
   self.assertEqual(len(list(collector.collect(healed[-1].next_cursor))),1)
 def test_interrupted_run_is_finished_before_success_and_cursor_does_not_advance_on_failure(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store('sqlite:///'+tmp+'/db',tmp+'/assets')
   with store.engine.begin() as c:c.execute(insert(runs).values(id='old',source='example',started_at=utcnow(),status='running',records=0))
   def fail(*args):
    yield Batch(records=[Record('one','note',{}, {})],next_cursor={'wrong':True})
    raise TimeoutError()
   with patch.object(runner,'adapter') as a:
    a.return_value.collect.side_effect=fail
    with self.assertRaises(TimeoutError):runner.run(store,'example',{'adapter':'files'})
   self.assertEqual(store.cursor('example'),{})
   with patch.object(runner,'adapter') as a:
    a.return_value.collect.return_value=[Batch(next_cursor={'complete':True})]
    runner.run(store,'example',{'adapter':'files'})
   with store.engine.connect() as c:states=c.execute(select(runs.c.status)).scalars().all()
   self.assertEqual(states,['failed','failed','ok']);self.assertEqual(store.cursor('example'),{'complete':True})
 def test_duplicate_batch_touches_freshness_without_reloading_bodies(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store('sqlite:///'+tmp+'/db',tmp+'/assets');store.register('s','owner','files','explicit_only')
   batch=Batch([Record(str(i),'note',{'text':'content'}, {}) for i in range(20)])
   self.assertEqual(store.ingest('s',batch)['changed'],20)
   queries=[]
   event.listen(store.engine,'before_cursor_execute',lambda c,cur,q,p,ctx,m:queries.append(q))
   self.assertEqual(store.ingest('s',batch)['duplicates'],20)
   self.assertLess(len(queries),10)
   self.assertFalse(any('hub_records.raw' in q for q in queries))
 def test_status_has_bounded_queries_and_keeps_source_counts_and_history(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Store('sqlite:///'+tmp+'/db',tmp+'/assets')
   for source in ('one','two'):
    store.register(source,'owner','files','explicit_only')
    store.ingest(source,Batch([Record('same','note',{}, {})]))
    with store.engine.begin() as c:c.execute(insert(runs).values(id=source,source=source,started_at=utcnow(),status='ok',records=1))
   queries=[]
   event.listen(store.engine,'before_cursor_execute',lambda c,cur,q,p,ctx,m:queries.append(q))
   result=store.status()
   self.assertEqual([r['count'] for r in result],[1,1])
   self.assertEqual([r['last_run']['status'] for r in result],['ok','ok'])
   self.assertTrue(all(r['last_observed_at'] for r in result))
   self.assertEqual(len(queries),4)
 def test_a_slow_source_does_not_block_another_and_timeout_retries(self):
  clock=[0];completed=[];spawned=[]
  class Process:
   def __init__(self,args,**kwargs):self.source=args[-1];self.pid=len(spawned)+100;self.stopped=False;spawned.append(self.source)
   def poll(self):return 1 if self.stopped else (0 if self.source=='fast' else None)
  def sleep(_):
   clock[0]+=16
   if clock[0]>100:raise KeyboardInterrupt
  with patch.object(scheduler.subprocess,'Popen',Process),patch.object(scheduler.time,'monotonic',side_effect=lambda:clock[0]),patch.object(scheduler.time,'sleep',side_effect=sleep),patch.object(scheduler,'stop_worker',side_effect=lambda p:setattr(p,'stopped',True)),patch.object(scheduler,'interrupted',side_effect=lambda *args:completed.append(args[1])):
   scheduler.serve(None,{'processing_enabled':False,'sources':{'slow':{'run_timeout_seconds':30,'interval_seconds':900},'fast':{'interval_seconds':900}}})
  self.assertIn('fast',spawned);self.assertGreater(spawned.count('slow'),1);self.assertIn('slow',completed)

if __name__=='__main__':unittest.main()
