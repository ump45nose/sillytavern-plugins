from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from hub_api.configuration import preferences
from hub_api.sources.base import Adapter
from test_records import NOW


def auth(settings): return {'Authorization':'Bearer '+settings.dev_token.get_secret_value()}


def test_documents_conflict_limits_defaults_and_concurrent_writers(settings):
    app=create_app(settings,adapters=[],now=lambda:NOW)
    with TestClient(app) as client:
        h=auth(settings)
        assert client.get('/api/v1/layout',headers=h).status_code==404
        default=client.get('/api/v1/preferences',headers=h).json()
        assert default['version']==0 and default['document']['step_goal']==8600
        conflict=client.put('/api/v1/preferences',headers={**h,'If-Match':'99'},json={'document':{}})
        assert conflict.status_code==409 and conflict.json()['current']==default
        value={'pages':[{'title':'测试','custom':{'future':True}}]}
        first=client.put('/api/v1/layout',headers={**h,'If-Match':'0'},json={'document':value})
        assert first.status_code==200 and first.json()['document']==value
        conflict=client.put('/api/v1/layout',headers={**h,'If-Match':'0'},json={'document':{}})
        assert conflict.status_code==409 and conflict.json()['current']==first.json()
        assert client.put('/api/v1/layout',headers=h,json={'document':{}}).status_code==400
        assert client.put('/api/v1/layout',headers={**h,'If-Match':'1'},json={'document':{'x':'x'*65536}}).status_code==400
        assert client.put('/api/v1/layout',headers={**h,'If-Match':'1'},content='{"document":{"x":NaN}}').status_code==400
        assert client.put('/api/v1/preferences',headers={**h,'If-Match':'0'},json={'document':{'token_limit_percent':101}}).status_code==400
        def write(i): return client.put('/api/v1/layout',headers={**h,'If-Match':'1'},json={'document':{'writer':i}}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool: statuses=list(pool.map(write,[1,2]))
        assert sorted(statuses)==[200,409]
        pref=client.put('/api/v1/preferences',headers={**h,'If-Match':'0'},json={'document':{'step_goal':9000,'month_budget':6000}})
        assert pref.status_code==200 and pref.json()['document']['exercise_goal']==45
        assert preferences(app.state.store)['step_goal']==9000


def test_subscriptions_matching_annual_price_and_goals(settings):
    settings.records_token=SecretStr('SENTINEL-RECORDS')
    calls=[]
    def handle(r):
        calls.append(r)
        assert r.method=='GET'
        return httpx.Response(200,json={'records':[
            {'id':'1','item':'ChatGPT subscription','occurred_at':'2026-10-19T20:00:00+08:00','amount':'140.00'},
            {'id':'2','merchant':'ChatGPT','occurred_at':'2026-09-19T20:00:00+08:00','amount':'130.00'}], 'next_offset':None})
    app=create_app(settings,now=lambda:NOW,transport=httpx.MockTransport(handle))
    with TestClient(app) as client:
        h=auth(settings)
        assert client.get('/api/v1/subscriptions',headers=h).json()=={'items':[],'monthly_total':0}
        assert not calls
        items=[{'id':'a','name':'chatgpt','price':1680,'currency':'CNY','cycle':'year','next_renewal':'2026-10-24'},
               {'id':'b','name':'Unknown','price':12,'cycle':'month'}]
        r=client.put('/api/v1/subscriptions',headers=h,json={'items':items})
        assert r.status_code==200
        assert r.json()['monthly_total']==152
        assert r.json()['items'][0]['last_charge']=={'date':'2026-10-19','amount':140}
        assert r.json()['items'][1]['last_charge'] is None
        assert len(calls)==1 and calls[0].url.params['status']=='confirmed'
        assert client.put('/api/v1/subscriptions',headers=h,json={'items':[items[0],items[0]]}).status_code==400
        assert client.put('/api/v1/subscriptions',headers=h,json={'items':[{**items[0],'currency':'USD'}]}).status_code==400
    # Goals are assembled after source caching; changing preferences never needs a source refetch.
    async def health(): return {'steps':123}
    async def bills(): return {'today_total':10}
    app=create_app(settings,adapters=[Adapter('records_health','h',60,health),Adapter('records_bills','b',60,bills)],now=lambda:NOW)
    with TestClient(app) as client:
        h=auth(settings)
        client.put('/api/v1/preferences',headers={**h,'If-Match':'0'},json={'document':{'step_goal':9000,'month_budget':6000}})
        data=client.get('/api/v1/modules?ids=health,bills',headers=h).json()['modules']
        assert data['health']['data']['step_goal']==9000 and data['bills']['data']['month_budget']==6000


def test_custom_cycle_keeps_today_outside_the_cycle(settings):
    settings.crm_token=SecretStr('SENTINEL-CRM')
    settings.plaud_token=SecretStr('SENTINEL-PLAUD')
    ranges=[]
    def handle(r):
        path=r.url.path
        if path.endswith('/people'):
            return httpx.Response(200,json={'items':[],'next_cursor':None})
        if path.endswith('/interactions'):
            ranges.append((r.url.params['start'],r.url.params['end']))
            day=r.url.params['start']
            return httpx.Response(200,json={'items':[{'id':day,'person_ids':['p'],'date':day,'channel':'phone','started_at':day+'T10:00:00+08:00','ended_at':None,'preview':'hi','attachment_count':0}], 'next_cursor':None})
        if path.endswith('/archives'):
            return httpx.Response(200,json={'items':[]})
        raise AssertionError(path)
    app=create_app(settings,now=lambda:NOW,transport=httpx.MockTransport(handle))
    with TestClient(app) as client:
        h=auth(settings)
        client.put('/api/v1/preferences',headers={**h,'If-Match':'0'},json={'document':{'cycle_start':'2026-07-01'}})
        crm=client.get('/api/v1/modules/crm',headers=h).json()['data']
        assert ranges==[('2026-07-01','2026-08-11'),('2026-10-20','2026-10-20')]
        assert crm['cycle']['start']=='2026-07-01' and crm['cycle']['interactions']==1
        assert len(crm['today'])==1


async def test_config_invalidation_waits_for_old_read(settings):
    import asyncio
    from hub_api.sources.base import SourceManager
    started,release=asyncio.Event(),asyncio.Event()
    async def fetch(): started.set();await release.wait();return {'old':True}
    manager=SourceManager([Adapter('crm','crm',60,fetch)],lambda:NOW)
    read=asyncio.create_task(manager.get('crm'))
    await started.wait()
    invalidation=asyncio.create_task(manager.invalidate('crm'))
    await asyncio.sleep(0)
    assert not invalidation.done()
    release.set();await read;await invalidation
    assert 'crm' not in manager.cache and 'crm' not in manager.states
