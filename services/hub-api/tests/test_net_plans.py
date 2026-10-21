from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from hub_api.app import create_app
from hub_api.modules.net import assemble
from hub_api.sources.base import Adapter
from test_configuration import auth
from test_records import NOW


def test_plans_persist_invalidate_and_drive_cached_attention(settings):
    calls = []
    async def usage():
        calls.append(1)
        return {'net': {'month_bytes': 95, 'today': {}, 'hourly': []}}
    app = create_app(settings, adapters=[Adapter('usage', 'network', 30, usage)], now=lambda: NOW)
    with TestClient(app) as client:
        h = auth(settings)
        assert client.get('/api/v1/net/plans').status_code == 401
        assert client.get('/api/v1/net/plans', headers=h).json() == {'items': []}
        client.get('/api/v1/modules/net', headers=h)
        plan = {'id': 'a', 'name': '主力', 'total_bytes': 100, 'expires_on': '2026-10-22'}
        r = client.put('/api/v1/net/plans', headers=h, json={'items': [plan]})
        assert r.status_code == 200 and r.json()['items'][0]['reset_day'] == 1
        assert 'usage' not in app.state.sources.cache
        assert client.get('/api/v1/net/plans', headers=h).json() == r.json()
        pools = client.get('/api/v1/modules/net', headers=h).json()['data']['pools']
        assert pools == [{**plan, 'used_bytes': 95, 'period_start': '2026-10-01',
                          'period_end': '2026-10-31', 'source': 'manual'}]
        rows = client.get('/api/v1/modules/attention', headers=h).json()['data']['items']
        assert [r['id'] for r in rows] == ['traffic-low:a'] and len(calls) == 2
        # Expiry and low quota each obey the configured preferences, using the same cache.
        client.put('/api/v1/preferences', headers={**h, 'If-Match': '0'}, json={
            'document': {'traffic_remaining_percent': 4, 'traffic_expiry_days': 1}})
        assert client.get('/api/v1/modules/attention', headers=h).json()['data']['items'] == []
        assert len(calls) == 2
    reopened = create_app(settings, adapters=[], now=lambda: NOW)
    with TestClient(reopened) as client:
        assert client.get('/api/v1/net/plans', headers=auth(settings)).json()['items'][0]['id'] == 'a'


@pytest.mark.parametrize('change', [
    {'id': ''}, {'id': 'a'*65}, {'name': ''}, {'name': 'a'*101}, {'total_bytes': 0},
    {'total_bytes': -1}, {'reset_day': 0}, {'reset_day': 29}, {'expires_on': '2026-02-30'},
    {'unexpected': True},
])
def test_invalid_plan_does_not_save(settings, change):
    app = create_app(settings, adapters=[], now=lambda: NOW)
    with TestClient(app) as client:
        plan = {'id': 'a', 'name': 'plan', 'total_bytes': 100, **change}
        assert client.put('/api/v1/net/plans', headers=auth(settings), json={'items': [plan]}).status_code == 400
        assert app.state.store.document('net_plans') is None


def test_plan_count_uniqueness_and_shared_unknown_counter(settings):
    app = create_app(settings, adapters=[], now=lambda: NOW)
    plan = {'id': 'a', 'name': 'plan', 'total_bytes': 100}
    with TestClient(app) as client:
        for items in ([plan, plan], [{**plan, 'id': str(i)} for i in range(6)]):
            assert client.put('/api/v1/net/plans', headers=auth(settings), json={'items': items}).status_code == 400
    plans = [{**plan, 'reset_day': 1, 'expires_on': None}, {**plan, 'id': 'b', 'reset_day': 1, 'expires_on': None}]
    assert [p['used_bytes'] for p in assemble({'net': {'month_bytes': 95}}, plans, NOW)['pools']] == [95, 95]
    assert all(p['used_bytes'] is None for p in assemble(None, plans, NOW)['pools'])


@pytest.mark.parametrize('now,reset,start,end', [
    ('2026-01-01', 28, '2025-12-28', '2026-01-27'),
    ('2026-02-28', 28, '2026-02-28', '2026-03-27'),
    ('2028-03-01', 1, '2028-03-01', '2028-03-31'),
])
def test_billing_period_boundaries_no_noncalendar_estimation(now, reset, start, end):
    plan = {'id': 'a', 'name': 'p', 'total_bytes': 10, 'reset_day': reset, 'expires_on': None}
    pool = assemble({'net': {'month_bytes': 5}}, [plan], datetime.fromisoformat(now))['pools'][0]
    assert (pool['period_start'], pool['period_end']) == (start, end)
    assert pool['used_bytes'] == (5 if reset == 1 else None)
