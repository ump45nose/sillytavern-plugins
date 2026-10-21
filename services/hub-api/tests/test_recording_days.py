import asyncio
from types import SimpleNamespace
from datetime import timedelta

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from test_configuration import auth
from test_records import NOW


def test_recording_days_cursor_metadata_people_cache_and_concurrency(settings, monkeypatch):
    settings.plaud_token = SecretStr('SENTINEL-PLAUD')
    settings.crm_token = SecretStr('SENTINEL-CRM')
    clock = [100.0]
    monkeypatch.setattr('hub_api.recording_days.time', SimpleNamespace(monotonic=lambda: clock[0]))
    calls, active, peak = [], [0], [0]
    async def handle(r):
        calls.append(r)
        path = r.url.path
        assert r.method == 'GET' and 'transcript' not in path and '/audio/' not in path
        if path.endswith('/archives'):
            assert r.url.params['audio_only'] == 'true'
            end = r.url.params['end_date']
            days = [(NOW.date()-timedelta(days=i)).isoformat() for i in range(8)]
            return httpx.Response(200, json={'items': [{'date': d, 'audio_count': 1} for d in days if d <= end][:int(r.url.params['limit'])]})
        if '/archives/' in path:
            assert r.url.params['metadata_only'] == 'true'
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            await asyncio.sleep(.01)
            active[0] -= 1
            day = path.rsplit('/', 1)[1]
            return httpx.Response(200, json={'date': day, 'has_transcript': day != '2026-10-19', 'audio': [
                {'id': 'a'*32, 'name': '录音', 'start_at': day+'T09:00:00+08:00', 'duration_ms': 3600000}]})
        if path.endswith('/people'):
            return httpx.Response(200, json={'items': [{'id': 'p', 'name': '张三'}, {'id': 'q', 'name': '李四'}], 'next_cursor': None})
        if path.endswith('/interactions'):
            return httpx.Response(200, json={'items': [
                {'date': '2026-10-20', 'person_ids': ['p', 'p'], 'started_at': '2026-10-20T09:30:00+08:00', 'ended_at': None},
                {'date': '2026-10-20', 'person_ids': ['q'], 'started_at': '2026-10-20T10:00:00+08:00', 'ended_at': None},
            ], 'next_cursor': None})
        raise AssertionError(path)
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        h = auth(settings)
        assert client.get('/api/v1/recordings').status_code == 401
        page = client.get('/api/v1/recordings?limit=5', headers=h)
        assert page.status_code == 200
        body = page.json()
        assert len(body['days']) == 5 and body['next_before'] == '2026-10-16'
        day = body['days'][0]
        assert day['date'] == '2026-10-20' and day['people'] == ['张三']
        assert day['recordings'][0] == {'id': 'plaud:2026-10-20:'+'a'*32, 'title': '录音',
                                      'start_at': '2026-10-20T09:00:00+08:00', 'duration_seconds': 3600}
        assert body['days'][1]['has_transcript'] is False
        assert 1 < peak[0] <= 4
        count = len(calls)
        assert client.get('/api/v1/recordings?limit=5', headers=h).json() == body
        assert len(calls) == count
        clock[0] += 61
        assert client.get('/api/v1/recordings?limit=5', headers=h).status_code == 200
        assert len(calls) > count
        last = client.get('/api/v1/recordings?before=2026-10-16&limit=5', headers=h).json()
        assert len(last['days']) == 3 and last['next_before'] is None
        assert last['days'][0]['date'] == '2026-10-15'
        for query in ('limit=0', 'limit=31', 'before=invalid', 'source=crm'):
            assert client.get('/api/v1/recordings?'+query, headers=h).status_code == 400


def test_recording_empty_and_upstream_errors_are_bounded(settings, caplog):
    settings.plaud_token = SecretStr('SENTINEL-PLAUD')
    def handle(r):
        if r.url.params.get('end_date') == '2026-10-19':
            return httpx.Response(503, text='SENTINEL-PLAUD')
        return httpx.Response(200, json={'items': []})
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        h = auth(settings)
        assert client.get('/api/v1/recordings', headers=h).json() == {'days': [], 'next_before': None}
        error = client.get('/api/v1/recordings?before=2026-10-20', headers=h)
        assert error.status_code == 502 and 'SENTINEL' not in error.text+caplog.text
