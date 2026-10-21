from datetime import timedelta
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from hub_api.app import create_app
from hub_api.sources.base import Adapter
from test_records import NOW


def test_all_rules_cache_only_dismiss_snooze_and_new_episode(settings):
    clock=[NOW]
    async def forbidden(): raise AssertionError('attention must not fetch')
    names=['token','usage','github','crm','records_health','records_bills']
    app=create_app(settings,adapters=[Adapter(n,n,60,forbidden) for n in names],now=lambda:clock[0])
    manager=app.state.sources
    old=lambda **kw:(NOW-timedelta(**kw)).isoformat()
    wait={'id':'git-waiting:I:reply','title':'reply','repo':'o/r','url':'https://github.com/o/r/issues/1','since':old(hours=25)}
    block={'id':'pr-blocked:P:conflict','title':'conflict','repo':'o/r','url':'https://github.com/o/r/pull/2','since':old(days=4)}
    values={'token':{'limits':[{'tool':'codex','windows':[{'label':'5h','percent':80,'resets_at':None}]}]},
        'usage':{'net':{'pools':[{'id':'a','name':'pool','total_bytes':100,'used_bytes':95,'expires_on':'2026-10-22'}]}},
        'github':{'waiting':[wait],'blocked':[block],'activity':{},'_partial':False},
        'crm':{'people':{'p':{'name':'Person','last_interaction_date':'2026-09-01'}},'recent':[],'cycle':{'people':1,'interactions':1}},
        'records_bills':{}}
    for n,v in values.items():
        manager.cache[n]={'data':v,'updated_at':NOW.isoformat() if n!='records_bills' else old(hours=7)}
        manager.states[n]={'status':'ok','checked_at':NOW,'last_success':NOW.isoformat()}
    manager.states['records_health']={'status':'error','failed_since':NOW-timedelta(minutes=31)}
    app.state.store.put_document('subscriptions',{'items':[{'id':'a','name':'Service','price':12,'currency':'CNY','cycle':'month','next_renewal':'2026-10-24'}]},None,NOW.isoformat())
    h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
    with TestClient(app) as client:
        def attention(): return client.get('/api/v1/modules/attention',headers=h).json()['data']['items']
        rows=attention()
        assert {r['rule'] for r in rows}=={'token_limit','traffic_low','git_waiting','pr_blocked','subs_renew','stale_contact','source_down'}
        assert next(r for r in rows if r['rule']=='subs_renew')['subtitle']=='10月24日 续费'
        assert next(r for r in rows if r['rule']=='traffic_low')['subtitle']=='10月22日 到期'
        assert len([r for r in rows if r['rule']=='source_down'])==2
        assert client.post('/api/v1/attention/'+wait['id']+'/dismiss',headers=h).status_code==204
        assert wait['id'] not in {r['id'] for r in attention()}
        assert client.get('/api/v1/modules/git',headers=h).json()['data']['waiting']==[]
        assert client.post('/api/v1/attention/'+block['id']+'/snooze',headers=h,json={'until':(NOW+timedelta(hours=1)).isoformat()}).status_code==204
        assert block['id'] not in {r['id'] for r in attention()}
        clock[0]+=timedelta(hours=2)
        assert block['id'] in {r['id'] for r in attention()}
        assert client.post('/api/v1/attention/missing/dismiss',headers=h).status_code==404
        assert client.post('/api/v1/attention/'+block['id']+'/snooze',headers=h,json={'until':NOW.isoformat()}).status_code==400
        manager.cache['github']['data']['waiting']=[]
        attention()
        manager.cache['github']['data']['waiting']=[wait]
        assert wait['id'] in {r['id'] for r in attention()}
        # Unknown onset begins with local observation; it cannot instantly look 3 days old.
        manager.cache['github']['data']['blocked'][0]['since']=None
        manager.cache['github']['data']['blocked'][0]['id']='pr-blocked:NEW:conflict'
        assert 'pr-blocked:NEW:conflict' not in {r['id'] for r in attention()}
        states=app.state.store.observe_attention({},set(),clock[0].isoformat())
        assert states['pr-blocked:NEW:conflict']['since']==clock[0].isoformat()


@pytest.mark.parametrize('provider,label,expected',[
    ('cursor','Cursor Models','Cursor Models'),
    ('cursor','cursor Models','Cursor Models'),
    ('cursor','Other Models','Cursor Other Models'),
    ('cursor','Cursorless','Cursor Cursorless'),
    ('codex','weekly','Codex weekly'),
    ('antigravity','Gemini 5-hour','Antigravity Gemini 5-hour'),
    ('copilot','Chat','Copilot Chat'),
    ('zai','5h','Z.ai 5h'),
])
def test_limit_attention_names_and_stable_identifiers(settings,provider,label,expected):
    async def forbidden(): raise AssertionError('attention must not fetch')
    app=create_app(settings,adapters=[Adapter('token','Token Monitor',30,forbidden)],now=lambda:NOW)
    source={'limits':[{'tool':provider,'windows':[{'label':label,'percent':100,'resets_at':None}]}]}
    before=deepcopy(source)
    app.state.sources.cache['token']={'data':source,'updated_at':NOW.isoformat()}
    h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
    identifier=f'token-limit:{provider}:{label}:'
    with TestClient(app) as client:
        row=client.get('/api/v1/modules/attention',headers=h).json()['data']['items'][0]
        assert row['title']==expected+' 额度已用 100%'
        assert row['id']==identifier
        assert row['subtitle'] is None
        assert client.post('/api/v1/attention/'+identifier+'/dismiss',headers=h).status_code==204
        assert client.get('/api/v1/modules/attention',headers=h).json()['data']['items']==[]
    assert source==before


@pytest.mark.parametrize('reset,expected',[
    ('2026-10-20T12:00:00Z','20:00 重置'),
    ('2026-10-20T16:30:00Z','明天 00:30 重置'),
    ('2026-10-22T12:00:00Z','10月22日 20:00 重置'),
    ('2027-01-01T12:00:00Z','2027年1月1日 20:00 重置'),
    (None,None),
    ('invalid',None),
])
def test_limit_reset_subtitle_uses_local_time_without_changing_source(settings,reset,expected):
    app=create_app(settings,adapters=[],now=lambda:NOW)
    source={'limits':[{'tool':'cursor','windows':[{'label':'Cursor Models','percent':100,'resets_at':reset}]}]}
    before=deepcopy(source)
    app.state.sources.cache['token']={'data':source,'updated_at':NOW.isoformat()}
    h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
    with TestClient(app) as client:
        row=client.get('/api/v1/modules/attention',headers=h).json()['data']['items'][0]
        assert row['subtitle']==expected
        assert row['id']==f'token-limit:cursor:Cursor Models:{reset or ""}'
        assert row['since']==NOW.isoformat()
    assert source==before
