from copy import deepcopy
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from hub_api.app import create_app
from hub_api.sources.base import Adapter
from test_records import NOW


def stage(status='none'):
    return {'mainline':None,'cycle':None if status=='closed' else {'id':'C1','index':1,'status':'active',
        'starts_at':(NOW-timedelta(days=40)).isoformat(),'ends_at':(NOW+timedelta(days=1)).isoformat(),
        'preclose_at':NOW.isoformat(),'day':41,'total':42},'goals':[],
        'reviews':{'daily':{'id':'daily:2026-10-20','label':'2026-10-20','status':'open',
            'prepared_at':NOW.isoformat(),'expires_at':(NOW+timedelta(minutes=45)).isoformat(),'memo_name':None},
            'weekly':{'id':'weekly:2026-W43','label':'2026-W43','status':'open','prepared_at':NOW.isoformat(),
                'expires_at':(NOW+timedelta(hours=2)).isoformat(),'memo_name':None},
            'next_daily_at':None,'next_weekly_at':None},
        'close':{'status':status,'cycle_id':'C1','template':'模板' if status in ('preclose','awaiting_close') else None}}


@pytest.mark.parametrize('close',['none','preclose','awaiting_close','closed'])
def test_goals_and_three_attention_rules(settings,close):
    settings.review_token=SecretStr('SENTINEL-REVIEW')
    value=stage(close)
    calls=[]
    def handle(request):
        assert request.headers['Authorization']=='Bearer SENTINEL-REVIEW'
        calls.append(request.url.path)
        return httpx.Response(200,json=value)
    app=create_app(settings,now=lambda:NOW,transport=httpx.MockTransport(handle))
    h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
    with TestClient(app) as client:
        r=client.get('/api/v1/modules?ids=goals,attention',headers=h)
        assert r.status_code==200
        modules=r.json()['modules'];assert modules['goals']['status']=='ok'
        assert modules['goals']['data']==value
        rows=modules['attention']['data']['items'];by_id={x['id']:x for x in rows}
        assert by_id['review:daily:2026-10-20']['subtitle']=='45 分钟后过期'
        assert by_id['review:weekly:2026-W43']['subtitle']=='2 小时后过期'
        assert all(x['target']=={'module':'goals'} for x in rows)
        if close in ('preclose','awaiting_close'):
            row=by_id['stage:close:C1'];assert row['rule']=='stage_close'
            assert row['severity']==('critical' if close=='awaiting_close' else 'warn')
            assert row['subtitle']==('已过结案日，目标已冻结' if close=='awaiting_close' else '10/21 结案')
            if close=='awaiting_close': assert rows[0]['id']=='stage:close:C1'
        else: assert 'stage:close:C1' not in by_id
        assert client.post('/api/v1/attention/review:daily:2026-10-20/dismiss',headers=h).status_code==204
        assert 'review:daily:2026-10-20' not in str(client.get('/api/v1/modules/attention',headers=h).json())
        assert calls==['/v1/stage']


def test_review_source_partial_failure_stale_expiry_and_isolation(settings):
    settings.review_token=SecretStr('SENTINEL-REVIEW')
    clock=[NOW];failure=[False]
    def handle(request):
        return httpx.Response(503,text='SENTINEL-REVIEW') if failure[0] else httpx.Response(200,json=stage(),headers={'X-Review-Partial':'true'})
    app=create_app(settings,now=lambda:clock[0],transport=httpx.MockTransport(handle))
    async def health(): return {'steps':1}
    app.state.sources.adapters['records_health']=Adapter('records_health','Health',60,health)
    h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
    with TestClient(app) as client:
        values=client.get('/api/v1/modules?ids=goals,health',headers=h).json()['modules']
        assert values['goals']['status']=='partial' and '_partial' not in values['goals']['data']
        failure[0]=True;clock[0]+=timedelta(seconds=61)
        values=client.get('/api/v1/modules?ids=goals,health',headers=h).json()['modules']
        assert values['goals']['status']=='stale' and values['health']['status']=='ok'
        clock[0]+=timedelta(days=1)
        values=client.get('/api/v1/modules?ids=goals,health',headers=h).json()['modules']
        assert values['goals']['status']=='error' and values['goals']['data'] is None
        assert values['health']['status']=='ok'
        assert 'SENTINEL-REVIEW' not in str(values)


def test_review_proxy_preserves_validation_and_expiry_errors(settings):
    settings.review_token=SecretStr('SENTINEL-REVIEW')
    calls=[]
    def handle(request):
        calls.append(request)
        if request.method=='GET': return httpx.Response(200,json={'items':[]} if request.url.path=='/v1/reviews' else {'id':'daily:2026-10-20'})
        if request.url.path.endswith('expired/preview'):
            return httpx.Response(409,json={'error':{'code':'expired','message':'日报会话已经过期','field':None}})
        return httpx.Response(422,json={'error':{'code':'validation','message':'一句话总结不能超过 45 个字符','field':'一句话总结今天','internal':'SENTINEL-REVIEW'}})
    with TestClient(create_app(settings,now=lambda:NOW,transport=httpx.MockTransport(handle))) as client:
        h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
        assert client.get('/api/v1/review/sessions?kind=daily',headers=h).status_code==200
        assert client.get('/api/v1/review/sessions/daily:2026-10-20',headers=h).status_code==200
        r=client.post('/api/v1/review/sessions/daily:2026-10-20/preview',headers=h,json={'content':'原文'})
        assert r.status_code==422 and r.json()['error']['field']=='一句话总结今天'
        assert r.json()['error']['message']=='一句话总结不能超过 45 个字符'
        assert 'internal' not in r.text and 'SENTINEL-REVIEW' not in r.text
        assert client.post('/api/v1/review/sessions/expired/preview',headers=h,json={'content':'原文'}).status_code==409
        assert client.get('/api/v1/review/sessions').status_code==401
        assert client.get('/api/v1/review/sessions?kind=other',headers=h).status_code==400


def test_invalid_review_payload_is_source_failure(settings):
    settings.review_token=SecretStr('SENTINEL-REVIEW')
    with TestClient(create_app(settings,now=lambda:NOW,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))) as client:
        h={'Authorization':'Bearer '+settings.dev_token.get_secret_value()}
        r=client.get('/api/v1/modules?ids=goals,attention',headers=h)
        assert r.status_code==200 and r.json()['modules']['goals']['status']=='error'
        assert r.json()['modules']['attention']['status']=='ok'
