from datetime import timedelta
from urllib.parse import parse_qs

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hub_api.app import create_app
from test_records import NOW


def test_media_independent_failures_cover_signing_and_cookie_isolation(settings, caplog):
    settings.emby_token = SecretStr("SENTINEL-EMBY")
    settings.emby_user_id = "user"
    settings.navidrome_user = "user"
    settings.navidrome_password = SecretStr("SENTINEL-NAVIDROME")
    settings.moviepilot_token = SecretStr("SENTINEL-MOVIEPILOT")
    settings.moviepilot_url = settings.emby_url  # Same LAN host, different sources share cookie scope.
    settings.qbittorrent_user = "user"
    settings.qbittorrent_password = SecretStr("SENTINEL-QBIT")
    settings.media_signing_key = SecretStr("SENTINEL-SIGNING-KEY")
    clock = [NOW]
    def handle(request):
        path = request.url.path
        assert all(secret not in str(request.url) for secret in settings.secrets())
        if not path.startswith("/api/v2"):
            assert "cookie" not in request.headers
        if path.endswith("/Resume"):
            return httpx.Response(200, json={"Items": [{"Id": "1", "Name": "Episode", "SeriesName": "Series", "Type": "Episode", "ParentIndexNumber": 2, "IndexNumber": 5, "ImageTags": {"Primary": "tag"}, "UserData": {"PlayedPercentage": 42}}] * 10})
        if path.endswith("/Latest"):
            return httpx.Response(200, json=[])
        if path.endswith("getAlbumList2.view"):
            assert request.method == "POST" and parse_qs(request.content.decode())["type"] == ["recent"]
            return httpx.Response(200, json={"subsonic-response": {"status": "ok", "albumList2": {"album": [{"id": "album", "name": "Album", "artist": "Artist", "coverArt": "al-123"}]}}})
        if path == "/api/v1/download/":
            return httpx.Response(503, text="SENTINEL-MOVIEPILOT", headers={"Set-Cookie": "source_cookie=source-private; Path=/"})
        if path.endswith("/auth/login"):
            return httpx.Response(200, text="Ok.", headers={"Set-Cookie": "SID=qbit-private; Path=/"})
        if path.endswith("/torrents/info"):
            assert request.headers["cookie"] == "SID=qbit-private"
            return httpx.Response(200, json=[{"hash": "h", "name": "Download", "progress": 0.63, "state": "stalledDL", "dlspeed": 0, "eta": 8640000}])
        if path.endswith("/Images/Primary"):
            return httpx.Response(200, stream=httpx.ByteStream(b"image"), headers={"Content-Type": "image/jpeg"})
        if path.endswith("getCoverArt.view"):
            assert request.method == "POST"
            return httpx.Response(200, stream=httpx.ByteStream(b"cover"), headers={"Content-Type": "image/png"})
        raise AssertionError(path)
    app = create_app(settings, now=lambda: clock[0], transport=httpx.MockTransport(handle))
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + settings.dev_token.get_secret_value()}
        response = client.get("/api/v1/modules/media", headers=headers)
        assert response.status_code == 200 and response.json()["status"] == "partial"
        data = response.json()["data"]
        assert len(data["continue_watching"]) == 8
        assert data["continue_watching"][0]["progress"] == 0.42
        assert data["continue_watching"][0]["subtitle"] == "S2E5"
        assert data["downloads"][0]["state"] == "stalled" and data["downloads"][0]["eta_seconds"] is None
        assert {s["id"]: s["status"] for s in data["services"]} == {"emby": "ok", "navidrome": "ok", "moviepilot": "error", "qbittorrent": "ok"}
        ref = data["continue_watching"][0]["image"]
        response = client.get("/api/v1/media/image", params={"ref": ref}, headers=headers)
        assert response.status_code == 200 and response.content == b"image"
        navref = data["recent_albums"][0]["image"]
        assert client.get("/api/v1/media/image", params={"ref": navref}, headers=headers).content == b"cover"
        assert client.get("/api/v1/media/image", params={"ref": ref + "tamper"}, headers=headers).status_code == 400
        clock[0] += timedelta(hours=24, seconds=1)
        assert client.get("/api/v1/media/image", params={"ref": ref}, headers=headers).status_code == 400
        assert all(secret not in caplog.text for secret in settings.secrets())
