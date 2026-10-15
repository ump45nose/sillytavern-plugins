"""M2 regressions: synthetic messages, optional disposable PostgreSQL schemas."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import runpy
import threading
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import httpx

from sqlalchemy import delete, func, select, update
from personal_data_hub.contracts import Asset, Batch, Record, instant
from personal_data_hub.processing import conversations, insights
from personal_data_hub.processing.query import ContentChanged, ContentRemoved
from personal_data_hub.processing.schema import blocks, inputs, jobs, members, objects, model_calls, model_results
from personal_data_hub.processing.worker import drain
from personal_data_hub.server import create_app


class ConversationTests(runpy.run_path(str(Path(__file__).with_name('processing-test.py')))['ProcessingTests']):
    def setUp(self):
        super().setUp()
        self.store.register('wechat-test', 'owner', 'crm', 'explicit_only')
        self.cfg = {'conversation_model': {'enabled': True, 'model': 'test-model', 'url': 'http://test.invalid',
                    'min_messages': 1, 'min_chars': 1, 'daily_request_limit': 24}}

    def chat(self, eid='one', text='第一条正文', person='p1', account='a1', chat='wx1', at='2026-10-11T00:00:00Z', key=None, assets=None, legacy=False):
        raw = {'channel': 'wechat', 'person_id': person, 'direction': 'inbound', 'source_message_key': key or eid,
               'summary': '历史互动描述'}
        if not legacy:
            raw['message'] = {'account_namespace': account, 'conversation_id': chat,
                  'conversation_type': 'group' if chat.endswith('@chatroom') else 'direct',
                  'record': {'content': text, 'sender': '群成员甲', 'sender_wxid': 'member-a', 'msg_type': 1}}
        return self.store.ingest('wechat-test', Batch([Record(eid, 'interactions', raw, {}, instant(at), assets=assets or [])]))

    def chats(self): return self.query.page(variant='wechat_day')['items']

    def fake_model(self, cfg, material):
        return {'themes': [{'title': '测试讨论', 'description': '有依据的描述', 'block_keys': [material[0]['key']]}],
                'key_points': [{'text': '有依据的要点', 'block_keys': [material[-1]['key']]}]}, {'total_tokens': 10}

    def test_identity_person_account_day_and_order(self):
        self.chat('late', at='2026-10-11T01:00:00Z');self.chat('early', text='更早正文')
        self.chat('same-name', person='p2');self.chat('other-account', account='a2')
        self.chat('yesterday', at='2026-10-10T15:59:59Z')
        drain(self.store)
        self.assertEqual(len(self.chats()),4)
        item=next(item for item in self.chats() if self.query.detail(item['id'])['metadata']['message_count']==2)
        page=self.query.block_page(item['id'],item['revision'])
        self.assertEqual([block['text'] for block in page['blocks']],['更早正文','第一条正文'])
        self.assertEqual(len({block['metadata']['segment_id'] for block in page['blocks']}),2)
        self.assertEqual(self.query.detail(item['id'])['business_date'],'2026-10-11')

    def test_moving_before_first_publication_cleans_old_pending_scope(self):
        self.chat(); old=self.chats()[0]['id'];job=self.repository.claim();rows=self.repository.snapshot(job)
        self.chat(person='p2',at='2026-10-12T00:00:00Z')
        self.assertFalse(self.repository.publish(job,rows,conversations.process(rows)))
        drain(self.store)
        self.assertIsNone(self.query.detail(old));self.assertEqual(len(self.chats()),1)
        self.assertEqual(self.query.detail(self.chats()[0]['id'])['metadata']['person_id'],'p2')

    def test_late_insert_and_delete_fence_whole_scope_and_rebuild_remainder(self):
        self.chat();drain(self.store);item=self.chats()[0]
        self.chat('second',text='后来消息');job=self.repository.claim();rows=self.repository.snapshot(job)
        self.chat('third',text='迟到消息',at='2026-10-10T23:59:59Z')
        self.assertFalse(self.repository.publish(job,rows,conversations.process(rows)))
        drain(self.store);self.assertEqual(self.query.detail(item['id'])['metadata']['message_count'],3)
        self.store.ingest('wechat-test',Batch(deletions=['second']))
        with self.assertRaises(ContentRemoved):self.query.block_page(item['id'],item['revision'])
        drain(self.store);self.assertEqual(self.query.detail(item['id'])['metadata']['message_count'],2)
        self.assertEqual(self.query.page(query='后来消息')['items'],[])

    def test_dedupe_uses_source_identity_and_conflicts_are_retained(self):
        self.chat('one',key='stable');self.chat('duplicate',key='stable');self.chat('different',key='different')
        self.chat('conflict',text='不同正文',key='stable');drain(self.store)
        item=self.chats()[0];detail=self.query.detail(item['id'])
        self.assertEqual(detail['metadata']['message_count'],3)
        self.assertEqual(detail['metadata']['duplicate_records'],1)
        self.assertIn('conflicting_message_identity',detail['warnings'])
        evidence=self.query.evidence(item['id']);self.assertEqual(len(evidence['inputs']),4)

    def test_legacy_unknown_time_empty_and_media_fidelity(self):
        self.chat('legacy',legacy=True,at=None);self.chat('empty',text='',chat='group@chatroom',
            assets=[Asset('encrypted.dat',content=b'private encrypted bytes',media_type='application/vnd.wechat.encrypted-image')])
        drain(self.store)
        legacy=next(item for item in self.chats() if item['occurred_at'] is None)
        self.assertIn('historical_original_missing',legacy['warnings']);self.assertIsNone(legacy['business_date'])
        item=next(item for item in self.chats() if item['occurred_at'] is not None)
        block=self.query.block_page(item['id'],item['revision'])['blocks'][0]
        self.assertEqual(block['text'],'');self.assertEqual(block['metadata']['media_state'],'encrypted')
        self.assertEqual(block['metadata']['sender'],'群成员甲');self.assertEqual(block['metadata']['conversation_type'],'group')

    def test_transport_split_and_search_never_joins_distinct_messages(self):
        body='甲'*7998+'跨页命中'+'末尾'*10000
        self.chat(text=body);self.chat('two',text='消息乙')
        drain(self.store);item=self.chats()[0];blocks=self.query.block_page(item['id'],item['revision'])['blocks']
        self.assertEqual(''.join(b['text'] for b in blocks if b['metadata']['message_index']==0),body)
        self.assertTrue(self.query.page(query='跨页命中')['items'])
        self.assertFalse(self.query.page(query='末尾消息乙')['items'])

    def test_contact_name_dependency_and_evidence_pagination(self):
        self.store.ingest('wechat-test',Batch([Record('people:p1','people',{'id':'p1','display_name':'姓名甲'})]))
        self.chat();drain(self.store);item=self.chats()[0];self.assertIn('姓名甲',item['title'])
        first=self.query.evidence(item['id'],item['revision'],limit=1)
        second=self.query.evidence(item['id'],item['revision'],after=first['next_after'],limit=1)
        self.assertEqual(len(first['inputs']+second['inputs']),2)
        self.store.ingest('wechat-test',Batch([Record('people:p1','people',{'id':'p1','display_name':'姓名乙'})]))
        self.assertTrue(any(not r['current_matches'] for r in self.query.evidence(item['id'],item['revision'])['inputs']))
        drain(self.store);self.assertIn('姓名乙',self.chats()[0]['title'])

    def test_model_citations_budget_configuration_and_deletion(self):
        self.chat();drain(self.store);item=self.chats()[0]
        with patch.object(insights,'call_model',side_effect=self.fake_model):
            self.assertEqual(drain(self.store,lane='model',config=self.cfg)['published'],1)
        result=self.query.insights(item['id'],item['revision'],'test-model')
        self.assertEqual(result['state'],'ready');self.assertEqual(result['result']['model'],'test-model')
        self.assertEqual(self.query.insights(item['id'],item['revision'],'other-model')['state'],'model_changed')
        self.assertEqual(len(self.query.page()['items']),1)
        self.assertEqual(len(self.query.page(variant='wechat_insights')['items']),1)
        with self.store.engine.connect() as c:self.assertEqual(c.scalar(select(func.count()).select_from(model_calls)),1)
        self.store.ingest('wechat-test',Batch(deletions=['one']))
        self.assertEqual(self.query.page(variant='wechat_insights')['items'],[])

    def test_model_rejects_bad_citations_and_truncated_response(self):
        with self.assertRaisesRegex(ValueError,'model_citation_invalid'):
            insights.validate({'themes':[],'key_points':[{'text':'虚构','block_keys':['fake']}]},{'real'})
        with self.assertRaisesRegex(ValueError,'model_response_invalid'):
            insights.validate({'themes':'bad','key_points':[]},{'real'})
        token=Path(self.temp.name)/'demo-token';token.write_text('synthetic-model-token')
        cfg=self.cfg['conversation_model']|{'api_key_file':str(token)}
        real_client=httpx.Client
        response=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{
            'finish_reason':'length','message':{'content':'{}'}}]}))
        with patch.object(insights.httpx,'Client',side_effect=lambda **kw:real_client(transport=response,**kw)):
            with self.assertRaisesRegex(ValueError,'model_incomplete_response'):
                insights.call_model(cfg,[{'key':'real','text':'资料'}])

    def test_insights_http_auth_and_revision_errors(self):
        self.chat();drain(self.store);item=self.chats()[0]
        token=Path(self.temp.name)/'viewer';token.write_text('synthetic-viewer')
        with patch('personal_data_hub.server.store_from',return_value=self.store):
            app=create_app({'database_url':str(self.store.engine.url),'asset_root':str(self.store.root),'sources':{},
                            'hub_viewer_token_file':str(token)},webhook_only=True)
        with TestClient(app) as client:
            route='/api/v1/contents/'+item['id']+'/insights'
            self.assertEqual(client.get(route,params={'revision':item['revision']}).status_code,401)
            response=client.get(route,params={'revision':item['revision']},headers={'Authorization':'Bearer synthetic-viewer'})
            self.assertEqual(response.status_code,200);self.assertEqual(response.json()['state'],'pending')
            self.assertEqual(client.get(route,params={'revision':item['revision']+1},headers={'Authorization':'Bearer synthetic-viewer'}).status_code,409)
            app.state.hub_store.engine.dispose()

    def test_model_retry_reuses_valid_windows_and_delete_clears_cache(self):
        self.chat(text='甲'*16000);drain(self.store)
        calls=[]
        def flaky(cfg,material):
            calls.append(material[0]['key'])
            if len(calls)==2:raise RuntimeError('model_http_502')
            return self.fake_model(cfg,material)
        with patch.object(insights,'call_model',side_effect=flaky):
            self.assertEqual(drain(self.store,lane='model',config=self.cfg)['failed'],1)
        with self.store.engine.begin() as c:
            self.assertEqual(c.scalar(select(func.count()).select_from(model_results)),1)
            c.execute(update(jobs).where(jobs.c.processor==insights.PROCESSOR).values(state='pending'))
        with patch.object(insights,'call_model',side_effect=flaky):
            self.assertEqual(drain(self.store,lane='model',config=self.cfg)['published'],1)
        self.assertEqual(len(calls),3)
        item=self.chats()[0]
        self.assertEqual(self.query.insights(item['id'],item['revision'])['result']['cached_windows'],1)
        self.store.ingest('wechat-test',Batch(deletions=['one']))
        with self.store.engine.connect() as c:self.assertEqual(c.scalar(select(func.count()).select_from(model_results)),0)

    def test_model_cannot_cache_or_publish_after_source_delete(self):
        self.chat();drain(self.store);job=self.repository.claim(lane='model',lease_seconds=900)
        rows=self.repository.snapshot(job)
        def remove_during_call(cfg,material):
            self.store.ingest('wechat-test',Batch(deletions=['one']))
            return self.fake_model(cfg,material)
        with patch.object(insights,'call_model',side_effect=remove_during_call):
            content=insights.process_with_config(rows,self.store,job,self.cfg)
        self.assertFalse(self.repository.publish(job,rows,content))
        with self.store.engine.connect() as c:self.assertEqual(c.scalar(select(func.count()).select_from(model_results)),0)

    def test_partial_model_coverage_is_explicit_and_original_reading_complete(self):
        self.chat(text='长文'*16000);drain(self.store);item=self.chats()[0]
        cfg={'conversation_model':self.cfg['conversation_model']|{'max_windows':1,'window_chars':10000}}
        with patch.object(insights,'call_model',side_effect=self.fake_model):drain(self.store,lane='model',config=cfg)
        result=self.query.insights(item['id'],item['revision'])['result']
        self.assertFalse(result['complete']);self.assertEqual(result['scope'],'partial_conversation')
        self.assertLess(result['selected_blocks'],result['total_blocks'])
        self.assertEqual(self.query.detail(item['id'])['coverage']['body'],'original')

    def test_budget_limit_does_not_exhaust_retries_or_block_reading(self):
        self.chat();drain(self.store)
        cfg={'conversation_model':self.cfg['conversation_model']|{'daily_request_limit':0}}
        result=drain(self.store,lane='model',config=cfg);self.assertEqual(result['failed'],1)
        self.assertEqual(self.chats()[0]['processing']['state'],'ready')
        error=self.repository.status()['errors'][0]
        self.assertEqual(error['error_code'],'model_budget_exceeded');self.assertEqual(error['attempts'],0)

    def test_rebuild_one_processor_preserves_other_memberships_and_revisions(self):
        self.chat();drain(self.store);item=self.chats()[0]
        self.repository.rebuild(source='wechat-test',force=True,processor=insights.PROCESSOR)
        self.assertEqual(drain(self.store)['claimed'],0)
        self.assertEqual(self.query.detail(item['id'])['revision'],item['revision'])
        with patch.object(insights,'call_model',side_effect=self.fake_model):
            self.assertEqual(drain(self.store,lane='model',config=self.cfg)['published'],1)

    def test_batch_backfill_keeps_every_member_without_duplicate_scope_work(self):
        for index in range(20):self.chat(str(index),text='消息'+str(index))
        self.chat('account',account='a2')
        with self.store.engine.begin() as c:
            for table in (model_results,blocks,inputs,objects,members,jobs):c.execute(delete(table))
        result=self.repository.rebuild(source='wechat-test',limit=50)
        self.assertEqual(result['enqueued'],4)
        self.assertEqual(drain(self.store)['published'],2)
        details=[self.query.detail(item['id']) for item in self.chats()]
        self.assertEqual(sorted(item['metadata']['message_count'] for item in details),[1,20])
        self.assertEqual(self.repository.rebuild(source='wechat-test')['enqueued'],0)

    def test_postgres_aggregate_publish_delete_cannot_revive_removed_member(self):
        if not self.schema:self.skipTest('requires PostgreSQL')
        self.chat();self.chat('second');drain(self.store);item=self.chats()[0]
        self.chat(text='更新正文');job=self.repository.claim();rows=self.repository.snapshot(job)
        barrier=threading.Barrier(2)
        def publish():barrier.wait();return self.repository.publish(job,rows,conversations.process(rows))
        def remove():barrier.wait();return self.store.ingest('wechat-test',Batch(deletions=['second']))
        with ThreadPoolExecutor(2) as pool:
            a=pool.submit(publish);b=pool.submit(remove);a.result(timeout=15);b.result(timeout=15)
        self.assertIsNone(self.query.detail(item['id']));drain(self.store)
        self.assertEqual(self.query.detail(item['id'])['metadata']['message_count'],1)


if __name__=='__main__':unittest.main()
