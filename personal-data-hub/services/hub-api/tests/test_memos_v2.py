import json
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from test_configuration import auth
from test_records import NOW


def memo(identifier='one', creator='users/owner'):
    return {'name': 'memos/'+identifier, 'creator': creator, 'content': '正文', 'tags': ['想法'],
            'createTime': '2026-10-20T04:00:00Z', 'updateTime': '2026-10-20T05:00:00Z',
            'pinned': True, 'visibility': 'PRIVATE', 'credentials': 'SENTINEL-MEMOS',
            'attachments': [{'name': 'attachments/image1', 'filename': '照片.png', 'type': 'image/png'}]}


def source(calls):
    def handle(r):
        calls.append(r)
        path = r.url.path
        if path.endswith('/auth/me'):
            return httpx.Response(200, json={'user': {'name': 'users/owner'}})
        if path.endswith(':getStats'):
            return httpx.Response(200, json={'tagCount': {'想法': 1}})
        if path == '/api/v1/memos':
            if r.method == 'POST':
                return httpx.Response(200, json={**memo('new'), **json.loads(r.content)})
            return httpx.Response(200, json={'memos': [memo()], 'nextPageToken': 'opaque-next'})
        if path == '/file/attachments/image1/照片.png':
            return httpx.Response(200, stream=httpx.ByteStream(b'PNG'), headers={'Content-Type': 'image/png'})
        if path.startswith('/api/v1/memos/'):
            identifier = path.rsplit('/', 1)[-1]
            value = memo(identifier, 'users/other' if identifier == 'other' else 'users/owner')
            if r.method == 'PATCH':
                value.update(json.loads(r.content))
            return httpx.Response(200, json=value)
        raise AssertionError(path)
    return handle


def test_own_list_official_filters_cursor_and_full_memo(settings, caplog):
    settings.memos_token = SecretStr('SENTINEL-MEMOS')
    calls = []
    app = create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(source(calls)))
    with TestClient(app) as client:
        assert client.get('/api/v1/memos').status_code == 401
        tag = '想法" || creator != "users/owner'
        q = 'a" && true'
        r = client.get('/api/v1/memos', headers=auth(settings), params={
            'page_size': 2, 'page_token': 'opaque-in', 'tag': tag, 'q': q})
        assert r.status_code == 200 and r.json()['next_page_token'] == 'opaque-next'
        item = r.json()['items'][0]
        assert set(item) == {'id', 'created_at', 'updated_at', 'content', 'tags', 'visibility', 'pinned', 'url', 'attachments'}
        assert item['updated_at'] == '2026-10-20T13:00:00+08:00' and item['pinned'] is True
        assert item['attachments'] == [{'name': 'attachments/image1', 'filename': '照片.png', 'type': 'image/png'}]
        params = calls[-1].url.params
        assert params['page_size'] == '2' and params['page_token'] == 'opaque-in' and params['state'] == 'NORMAL'
        assert params['filter'] == '(creator == "users/owner") && ('+json.dumps(tag, ensure_ascii=False)+' in tags) && (content.contains('+json.dumps(q)+'))'
        assert len(calls) == 2  # one bounded list, no per-memo fetch or full-text scan
        assert client.get('/api/v1/memos/one', headers=auth(settings)).json() == item
        assert len([r for r in calls if r.url.path.endswith('/auth/me')]) == 1
        assert 'SENTINEL' not in r.text+caplog.text


def test_create_patch_and_archive_forward_once_and_invalidate(settings):
    settings.memos_token = SecretStr('SENTINEL-MEMOS')
    calls = []
    app = create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(source(calls)))
    with TestClient(app) as client:
        h = auth(settings)
        def warm():
            assert client.get('/api/v1/modules/memos', headers=h).json()['status'] == 'ok'
            assert 'memos' in app.state.sources.cache
        warm()
        r = client.post('/api/v1/memos', headers=h, json={'content': 'new'})
        assert r.status_code == 201 and r.json()['id'] == 'new' and r.json()['content'] == 'new'
        assert 'memos' not in app.state.sources.cache and 'memos' not in app.state.sources.states
        writes = [r for r in calls if r.method != 'GET']
        assert len(writes) == 1 and json.loads(writes[0].content) == {'content': 'new', 'visibility': 'PRIVATE'}
        warm()
        r = client.patch('/api/v1/memos/one', headers=h, json={'pinned': False, 'content': 'changed'})
        assert r.status_code == 200 and r.json()['pinned'] is False and r.json()['content'] == 'changed'
        assert 'memos' not in app.state.sources.cache
        patch = [r for r in calls if r.method == 'PATCH'][-1]
        assert set(patch.url.params['update_mask'].split(',')) == {'content', 'pinned'}
        warm()
        assert client.delete('/api/v1/memos/one', headers=h).status_code == 204
        assert 'memos' not in app.state.sources.cache
        writes = [r for r in calls if r.method != 'GET']
        assert len(writes) == 3 and all(r.method != 'DELETE' for r in writes)
        assert json.loads(writes[-1].content) == {'state': 'ARCHIVED'}
        assert writes[-1].url.params['update_mask'] == 'state'


def test_privileged_token_cannot_read_modify_archive_or_download_other_memo(settings):
    settings.memos_token = SecretStr('SENTINEL-MEMOS')
    calls = []
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(source(calls)))) as client:
        h = auth(settings)
        assert client.get('/api/v1/memos/other', headers=h).status_code == 404
        assert client.patch('/api/v1/memos/other', headers=h, json={'pinned': False}).status_code == 404
        assert client.delete('/api/v1/memos/other', headers=h).status_code == 404
        assert client.get('/api/v1/memos/other/attachments/image1', headers=h).status_code == 404
        before = len(calls)
        assert client.get('/api/v1/memos/!invalid', headers=h).status_code == 404
        assert client.get('/api/v1/memos/one/attachments/foreign', headers=h).status_code == 404
        assert all(r.method == 'GET' and not r.url.path.startswith('/file') for r in calls)
        assert len(calls) == before+1


@pytest.mark.parametrize('payload', [{}, {'content': None}, {'pinned': None}, {'pinned': 'false'}, {'state': 'ARCHIVED'}, {'content': ''}])
def test_invalid_patch_is_rejected_before_io(settings, payload):
    settings.memos_token = SecretStr('SENTINEL-MEMOS')
    calls = []
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(source(calls)))) as client:
        assert client.patch('/api/v1/memos/one', headers=auth(settings), json=payload).status_code == 400
        assert not calls


def test_attachment_proxy_is_bound_to_own_memo_and_never_follows_external_link(settings):
    settings.memos_token = SecretStr('SENTINEL-MEMOS')
    calls = []
    external = [False]
    base = source(calls)
    def handle(r):
        response = base(r)
        if r.url.path == '/api/v1/memos/one' and external[0]:
            value = response.json()
            value['attachments'][0]['externalLink'] = 'http://evil.invalid/private'
            return httpx.Response(200, json=value)
        return response
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(handle))) as client:
        url = '/api/v1/memos/one/attachments/attachments/image1'
        assert client.get(url).status_code == 401
        r = client.get(url, headers=auth(settings))
        assert r.status_code == 200 and r.content == b'PNG' and r.headers['cache-control'] == 'private, no-store'
        assert r.headers['content-type'] == 'image/png'
        external[0] = True
        count = len([r for r in calls if r.url.path.startswith('/file/')])
        assert client.get(url, headers=auth(settings)).status_code == 404
        assert len([r for r in calls if r.url.path.startswith('/file/')]) == count


def test_write_timeout_does_not_retry_and_discards_cached_module(settings, caplog):
    settings.memos_token = SecretStr('SENTINEL-MEMOS')
    calls = []
    base = source(calls)
    def fail(r):
        if r.method == 'POST':
            calls.append(r)
            raise httpx.ReadTimeout('SENTINEL-MEMOS', request=r)
        return base(r)
    app = create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(fail))
    with TestClient(app) as client:
        client.get('/api/v1/modules/memos', headers=auth(settings))
        r = client.post('/api/v1/memos', headers=auth(settings), json={'content': 'new'})
        assert r.status_code == 502 and len([r for r in calls if r.method == 'POST']) == 1
        assert 'memos' not in app.state.sources.cache and 'SENTINEL' not in r.text+caplog.text
