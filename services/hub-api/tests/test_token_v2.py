from datetime import timedelta

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from test_configuration import auth
from test_records import NOW


def fixtures():
    days = [{'date': (NOW.date()-timedelta(days=i)).isoformat(), 'tokens': 100-i, 'cost': (100-i)/100,
             'perClient': {'codex': {'tokens': 100-i, 'cost': (100-i)/100}},
             'perModel': {'model': {'tokens': 100-i, 'cost': (100-i)/100}}} for i in range(100)]
    sessions = {'codex:s'+str(i): {'title': 'title '+str(i), 'client': 'codex', 'totalTokens': i,
                'costUsd': i/100, 'models': {'model': i}, 'lastUsedAt': '2026-10-20T04:00:00Z',
                'projectId': '/private/project', 'projectLabel': 'PRIVATE-PROJECT', 'content': 'PRIVATE-CONTENT',
                'account': 'PRIVATE-ACCOUNT'} for i in range(25)}
    today = {'totalTokens': 1000, 'costUsd': 10, 'clients': {'codex': 900, 'cursor': 100},
             'clientCosts': {'codex': 9, 'cursor': 1}, 'models': {'model': 1000}, 'modelCosts': {'model': 10}, 'sessions': sessions}
    device = {'deviceId': 'mac', 'hostname': 'Mac', 'periods': {'today': today}, 'historyAvailable': True,
              'history': {'daily': days}, 'credentials': 'PRIVATE-KEY'}
    return {'/api/stats': {'periods': {'today': today, 'month': today}, 'devices': [device],
                           'sessionDetailsOmitted': {'month': 1}, 'historyPreview': {'daily': days[:30]}, 'limits': {}},
            '/api/history': {'daily': days}, '/api/devices': {'devices': [device]}}


def test_full_history_exact_ranges_top_sessions_and_minimal_cache(settings, caplog):
    settings.token_secret = SecretStr('SENTINEL-TOKEN')
    payloads = fixtures()
    calls = []
    def handle(r):
        calls.append(r.url.path)
        assert r.method == 'GET'
        return httpx.Response(200, json=payloads[r.url.path])
    app = create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))
    with TestClient(app) as client:
        h = auth(settings)
        day = client.get('/api/v1/modules/token', headers=h).json()['data']
        assert len(day['history']) == 100 and day['history'][0]['date'] == '2026-07-13'
        assert day['total'] == 1000 and day['cost'] == 10
        assert [t['id'] for t in day['tools']] == ['codex', 'cursor']
        assert day['models'] == [{'id': 'model', 'name': 'model', 'total': 1000, 'cost': 10, 'provider': None}]
        assert len(day['sessions']) == 20 and day['sessions'][0] == {
            'id': 'codex:s24', 'title': 'title 24', 'tool': 'codex', 'model': 'model', 'device': 'Mac',
            'total': 24, 'cost': .24, 'updated_at': '2026-10-20T12:00:00+08:00'}
        week = client.get('/api/v1/modules/token?range=week', headers=h).json()['data']
        total = 1000+sum(100-i for i in range(1, 7))
        assert week['total'] == total
        assert week['tools'][0]['total'] == total-100
        assert week['models'][0]['total'] == total and week['devices'][0]['total'] == total
        assert week['sessions'] is None
        month = client.get('/api/v1/modules/token?range=month', headers=h).json()['data']
        assert month['total'] == 1000+sum(100-i for i in range(1, 30))
        assert month['sessions'] is None and month['history'] == day['history']
        assert sorted(calls) == ['/api/devices', '/api/history', '/api/stats']
        retained = str(app.state.sources.cache)+str(day)+str(week)+str(month)+caplog.text
        for forbidden in ('PRIVATE-', 'SENTINEL-', 'projectId', 'projectLabel', 'credentials', 'account', 'content'):
            assert forbidden not in retained


def test_incomplete_history_keeps_unknown_and_source_failure_isolated(settings):
    settings.token_secret = SecretStr('SENTINEL-TOKEN')
    payloads = fixtures()
    payloads['/api/history']['daily'][3].pop('perModel')
    payloads['/api/devices']['devices'][0]['history']['daily'].pop(4)
    def handle(r): return httpx.Response(200, json=payloads[r.url.path])
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        week = client.get('/api/v1/modules/token?range=week', headers=auth(settings)).json()['data']
        assert week['models'] is None and week['devices'][0]['total'] is None
    def fail(r):
        return httpx.Response(503, text='SENTINEL-TOKEN') if r.url.path == '/api/history' else handle(r)
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(fail))) as client:
        body = client.get('/api/v1/modules?ids=token,subs', headers=auth(settings)).json()['modules']
        assert body['token']['status'] == 'error' and body['subs']['status'] == 'unconfigured'


def test_sessions_not_faked_for_omitted_details_or_multiple_models(settings):
    settings.token_secret = SecretStr('SENTINEL-TOKEN')
    payloads = fixtures()
    payloads['/api/stats']['periods']['today']['sessions']['codex:s24']['models']['other'] = 1
    def handle(r): return httpx.Response(200, json=payloads[r.url.path])
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        day = client.get('/api/v1/modules/token', headers=auth(settings)).json()['data']
        assert day['sessions'][0]['model'] is None
    payloads['/api/stats']['sessionDetailsOmitted']['today'] = 1
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        day = client.get('/api/v1/modules/token', headers=auth(settings)).json()['data']
        assert day['sessions'] is None
