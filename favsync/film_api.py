"""Small authenticated JSON API for film leads and user-owned download state."""

from __future__ import annotations

from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
import re
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .film_store import add_manual_film, get_film, list_films, set_downloaded
from .store import Store


def serve(cfg):
    store = Store(cfg["state_dir"])
    token = os.environ.get("FILM_API_TOKEN", "")
    if not token:
        store.close()
        raise ValueError("FILM_API_TOKEN is required")
    timezone = ZoneInfo(cfg["timezone"])
    host = cfg["film_api"]["bind_host"]
    port = cfg["film_api"]["port"]

    class Handler(BaseHTTPRequestHandler):
        server_version = "FavsyncFilmAPI/1"

        def log_message(self, *_):
            # Never log request headers or bodies. The API token stays private.
            pass

        def send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authenticated(self):
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, "Bearer " + token):
                self.send_json(401, {"error": "unauthorized"})
                return False
            return True

        def today(self):
            return datetime.now(timezone).date()

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == "/health":
                self.send_json(200, {"status": "ok"})
                return
            if not self.authenticated():
                return
            if path.path == "/v1/films":
                try:
                    params = parse_qs(path.query, keep_blank_values=True)
                    if set(params) - {"offset", "limit", "downloaded", "released"}:
                        raise ValueError
                    offset = int(params.get("offset", ["0"])[0])
                    limit = int(params.get("limit", ["50"])[0])
                    if offset < 0 or not 1 <= limit <= 200:
                        raise ValueError
                    downloaded = self._filter(params, "downloaded", allow_unknown=False)
                    released = self._filter(params, "released", allow_unknown=True)
                except (TypeError, ValueError):
                    self.send_json(400, {"error": "invalid_query"})
                    return
                self.send_json(200, list_films(store.db, self.today(), offset, limit, downloaded, released))
                return
            match = re.fullmatch(r"/v1/films/([1-9]\d*)", path.path)
            if match and not path.query:
                item = get_film(store.db, int(match.group(1)), self.today())
                self.send_json(200 if item else 404, item or {"error": "not_found"})
                return
            self.send_json(404, {"error": "not_found"})

        @staticmethod
        def _filter(params, name, allow_unknown):
            values = params.get(name)
            if values is None:
                return ... if allow_unknown else None
            if len(values) != 1:
                raise ValueError
            if values[0] == "true":
                return True
            if values[0] == "false":
                return False
            if allow_unknown and values[0] == "unknown":
                return None
            raise ValueError

        def do_PATCH(self):
            if not self.authenticated():
                return
            path = urlsplit(self.path)
            match = re.fullmatch(r"/v1/films/([1-9]\d*)/downloaded", path.path)
            if not match or path.query:
                self.send_json(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", ""))
                if not 1 <= size <= 1024:
                    raise ValueError
                payload = json.loads(self.rfile.read(size))
                if set(payload) != {"downloaded"} or type(payload["downloaded"]) is not bool:
                    raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError):
                self.send_json(400, {"error": "invalid_body"})
                return
            item = set_downloaded(store.db, int(match.group(1)), payload["downloaded"], self.today())
            self.send_json(200 if item else 404, item or {"error": "not_found"})

        def do_POST(self):
            if not self.authenticated():
                return
            if urlsplit(self.path).path != "/v1/films" or urlsplit(self.path).query:
                self.send_json(404, {"error": "not_found"})
                return
            try:
                size = int(self.headers.get("Content-Length", ""))
                if not 1 <= size <= 2048:
                    raise ValueError
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or set(payload) - {
                        "title", "release_year", "release_date", "country", "media_type"}:
                    raise ValueError
                title, year = payload.get("title"), payload.get("release_year")
                if not isinstance(title, str) or not title.strip() or len(title) > 120:
                    raise ValueError
                if type(year) is not int or not 1900 <= year <= 2100:
                    raise ValueError
                release = payload.get("release_date")
                if release is not None and (not isinstance(release, str) or
                                            date.fromisoformat(release).year != year):
                    raise ValueError
                country = payload.get("country")
                if country is not None and (not isinstance(country, str) or
                                            not country.strip() or len(country) > 60):
                    raise ValueError
                media_type = payload.get("media_type")
                if media_type is not None and media_type not in ("movie", "tv"):
                    raise ValueError
            except (TypeError, ValueError, json.JSONDecodeError):
                self.send_json(400, {"error": "invalid_body"})
                return
            film_id = add_manual_film(store.db, title, year, release,
                                      country.strip() if country else None, media_type)
            self.send_json(200, get_film(store.db, film_id, self.today()))

    try:
        server = HTTPServer((host, port), Handler)
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            server.server_close()
    finally:
        store.close()
