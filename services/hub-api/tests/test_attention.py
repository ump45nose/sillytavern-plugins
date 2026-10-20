from datetime import timedelta
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
