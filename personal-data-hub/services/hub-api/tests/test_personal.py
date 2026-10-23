import json

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from test_records import NOW

AUDIO = "a" * 32


def configured(settings):
    settings.crm_token = SecretStr("SENTINEL-CRM-READ")
    settings.crm_write_token = SecretStr("SENTINEL-CRM-WRITE")
    settings.plaud_token = SecretStr("SENTINEL-PLAUD-READ")
    settings.memos_token = SecretStr("SENTINEL-MEMOS")
    return settings


def source(request):
    path = request.url.path
    if path.endswith("/people"):
        return httpx.Response(200, json={"items": [{"id": "person1", "name": "张三", "relationship": "同事", "last_interaction_date": "2026-09-01"}], "next_cursor": None})
    if path.endswith("/interactions"):
        if request.method == "POST":
            assert request.headers["Authorization"] == "Bearer SENTINEL-CRM-WRITE"
            body = json.loads(request.content)
            assert body["person_ids"] == ["person1"] and body["date"] == "2026-10-20"
            assert body["content"] == "hello"
            return httpx.Response(201, json={"id": "new"})
        return httpx.Response(200, json={"items": [{"id": "interaction1", "person_ids": ["person1"], "channel": "wechat", "date": "2026-10-20", "started_at": "2026-10-20T09:00:00+08:00", "ended_at": "2026-10-20T09:20:00+08:00", "preview": "交流", "attachment_count": 0}], "next_cursor": None})
    if path.endswith("/archives"):
        return httpx.Response(200, json={"items": [{"date": "2026-10-20", "audio_count": 1}], "total": 1})
    if path.endswith("/archives/2026-10-20"):
        assert request.url.params['metadata_only'] == 'true'
        return httpx.Response(200, json={"audio": [{"id": AUDIO, "name": "录音", "start_at": "2026-10-20T08:50:00+08:00", "duration_ms": 2400000}]})
    if path.endswith("/auth/me"):
        return httpx.Response(200, json={"user": {"name": "users/1"}})
    if path.endswith(":getStats"):
        return httpx.Response(200, json={"tagCount": {"想法": 12}})
    if path.endswith("/memos"):
        if request.method == "POST":
            assert json.loads(request.content) == {"content": "hello", "visibility": "PRIVATE"}
            return httpx.Response(201, json={"name": "memos/new", "content": "hello", "creator": "users/1", "createTime": "2026-10-20T04:00:00Z"})
        assert request.url.params["page_size"] == "20"
        assert request.url.params["filter"] == '(creator == "users/1")'
        return httpx.Response(200, json={"memos": [{"name": "memos/one", "creator": "users/1", "createTime": "2026-10-20T04:00:00Z", "content": "hello", "tags": ["想法"], "visibility": "PRIVATE"}]})
    if "/audio/" in path:
        assert request.headers["Range"] == "bytes=0-3"
        return httpx.Response(206, stream=httpx.ByteStream(b"data"), headers={"Content-Range": "bytes 0-3/10", "Content-Type": "audio/mpeg"})
    if path.endswith("transcript.md"):
        return httpx.Response(200, text="# Transcript\nSENTINEL-PLAUD-READ")
    raise AssertionError(path)


def test_personal_normalization_writes_and_range_proxy(settings, caplog):
    settings = configured(settings)
    app = create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(source))
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + settings.dev_token.get_secret_value()}
        body = client.get("/api/v1/modules?ids=crm,memos", headers=headers).json()["modules"]
        assert body["crm"]["status"] == body["memos"]["status"] == "ok"
        crm = body["crm"]["data"]
        assert crm["today"][0]["recording"]["id"] == "plaud:2026-10-20:" + AUDIO
        assert crm["cycle"] == {"start": "2026-09-09", "days": 42, "people": 1, "interactions": 1, "recordings": 1}
        assert crm["stale"][0]["days"] == 49
        assert body["memos"]["data"]["tags"] == [{"name": "想法", "count": 12}]
        response = client.post("/api/v1/memos", headers=headers, json={"content": "hello", "visibility": "PRIVATE"})
        assert response.status_code == 201 and response.json()["id"] == "new"
        response = client.post("/api/v1/crm/interactions", headers=headers, json={"person_name": "张三", "channel": "微信", "summary": "hello", "occurred_at": "2026-10-19T18:00:00Z"})
        assert response.status_code == 201
        base = "/api/v1/recordings/plaud:2026-10-20:" + AUDIO
        response = client.get(base + "/audio", headers={**headers, "Range": "bytes=0-3"})
        assert response.status_code == 206 and response.content == b"data"
        assert response.headers["Content-Range"] == "bytes 0-3/10"
        assert response.headers['cache-control'] == 'private, no-store'
        assert response.headers['x-accel-buffering'] == 'no'
        response = client.get(base + "/transcript", headers=headers)
        assert response.status_code == 200 and response.headers["Content-Type"].startswith("text/markdown")
        assert "SENTINEL" not in response.text + caplog.text
        assert client.get(base + "/audio", headers={**headers, "Range": "invalid"}).status_code == 400
        assert client.get("/api/v1/recordings/http:evil/audio", headers=headers).status_code == 404


def test_partial_crm_keeps_other_source_and_null_fields(settings):
    settings = configured(settings)
    def fail_plaud(request):
        if "/archives" in request.url.path:
            return httpx.Response(503, text="SENTINEL-PLAUD-READ")
        return source(request)
    with TestClient(create_app(settings, now=lambda: NOW, transport=httpx.MockTransport(fail_plaud))) as client:
        response = client.get("/api/v1/modules?ids=crm,memos", headers={"Authorization": "Bearer " + settings.dev_token.get_secret_value()})
        crm = response.json()["modules"]["crm"]
        assert response.status_code == 200 and crm["status"] == "partial"
        assert crm["data"]["cycle"]["recordings"] is None
        assert crm["data"]["today"][0]["recording"] is None
        assert response.json()["modules"]["memos"]["status"] == "ok"
        assert "SENTINEL" not in response.text
