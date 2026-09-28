"""Small authenticated JSON API for film leads and user-owned download state."""

from __future__ import annotations

from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from .film_store import get_film, list_films, set_downloaded
from .store import Store


def ensure_token(state_dir):
    path = Path(state_dir) / "film-api-token"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32) + "\n")
            f.flush()
            os.fsync(f.fileno())
    token = path.read_text().strip()
    if len(token) < 32 or (path.stat().st_mode & 0o077):
        raise ValueError("film API token is missing or not private")
    return token


def serve(cfg):
    store = Store(cfg["state_dir"])
    token = ensure_token(cfg["state_dir"])
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

    try:
        server = HTTPServer((host, port), Handler)
        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            server.server_close()
    finally:
        store.close()
