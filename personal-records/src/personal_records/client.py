"""Small read-only HTTP client for existing cron and report consumers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RecordsClient:
    def __init__(self, base_url: str, token_file: str):
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError("records_api_url must be an HTTP service base URL")
        self.base_url, self.token_file = base_url.rstrip("/"), Path(token_file)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    @classmethod
    def from_config(cls, config: dict):
        if not config.get("records_api_url") or not config.get("records_token_file"):
            raise ValueError("configure records_api_url and records_token_file for Personal Records")
        return cls(config["records_api_url"], config["records_token_file"])

    @classmethod
    def from_file(cls, path=None):
        selected = path or os.environ.get("HERMES_CRON_CONFIG", "/home/yuwk/cron/env/hermes.local.json")
        return cls.from_config(json.loads(Path(selected).read_text()))

    def get(self, path: str, **params):
        token = self.token_file.read_text().strip()
        if not token: raise ValueError("records read credential is empty")
        query = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
        request = Request(self.base_url + path + ("?"+query if query else ""), headers={"Authorization": "Bearer "+token})
        with self.opener.open(request, timeout=20) as response:
            return json.load(response)

    def health_summary(self, start_date, end_date, metrics=None):
        return self.get("/api/v1/health/summary", start_date=start_date, end_date=end_date, metrics=metrics)

    def bill_summary(self, start_date, end_date, **filters):
        return self.get("/api/v1/bills/summary", start_date=start_date, end_date=end_date, **filters)

    def iter_bills(self, start_date, end_date, **filters):
        offset = 0
        while True:
            page = self.get("/api/v1/bills", start_date=start_date, end_date=end_date, offset=offset, limit=200, **filters)
            yield from page["records"]
            following = page["next_offset"]
            if following is None: return
            if not isinstance(following, int) or following <= offset: raise RuntimeError("records pagination did not advance")
            offset = following

    def source_status(self): return self.get("/api/v1/sources")
