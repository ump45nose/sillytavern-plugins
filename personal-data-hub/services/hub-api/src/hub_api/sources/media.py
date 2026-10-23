import asyncio
import base64
import hashlib
import hmac
import json
import re
import secrets

import httpx

from .base import Adapter


def encoded(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


class Media:
    def __init__(self, client, settings, now, transport=None):
        self.client, self.settings, self.now = client, settings, now
        # qBittorrent's SID is scoped to this source, never the shared LAN client.
        self.qbit = httpx.AsyncClient(timeout=settings.source_timeout_seconds, transport=transport, follow_redirects=False)

    def ref(self, source, identifier):
        if not self.settings.media_signing_key or identifier is None:
            return None
        if not re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", str(identifier)):
            return None
        payload = encoded(json.dumps({"s": source, "id": str(identifier), "e": int(self.now().timestamp()) + 86400}, separators=(",", ":")).encode())
        signature = encoded(hmac.new(self.settings.media_signing_key.get_secret_value().encode(), payload.encode(), hashlib.sha256).digest())
        return payload + "." + signature

    def parse_ref(self, ref):
        if not self.settings.media_signing_key:
            raise ValueError("images not configured")
        payload, signature = ref.split(".")
        expected = encoded(hmac.new(self.settings.media_signing_key.get_secret_value().encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid image signature")
        value = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if value["s"] not in ("emby", "navidrome") or value["e"] <= self.now().timestamp():
            raise ValueError("invalid image reference")
        if not re.fullmatch(r"[A-Za-z0-9_:-]{1,200}", value["id"]):
            raise ValueError("invalid image id")
        return value

    async def emby(self):
        url = self.settings.emby_url.rstrip("/") + "/emby"
        headers = {"X-Emby-Token": self.settings.emby_token.get_secret_value()}
        uid = self.settings.emby_user_id
        async def get(path, params):
            r = await self.client.get(url + path, headers=headers, params=params)
            r.raise_for_status()
            return r.json()
        watching, latest = await asyncio.gather(
            get("/Users/" + uid + "/Items/Resume", {"Limit": 8, "Fields": "RunTimeTicks", "MediaTypes": "Video"}),
            get("/Users/" + uid + "/Items/Latest", {"Limit": 8, "Fields": "RunTimeTicks", "IncludeItemTypes": "Movie,Episode"}))
        def item(row, progress=False):
            season, episode = row.get("ParentIndexNumber"), row.get("IndexNumber")
            subtitle = f"S{season}E{episode}" if row.get("Type") == "Episode" and season is not None and episode is not None else (str(row["ProductionYear"]) if row.get("ProductionYear") is not None else None)
            data = {"id": str(row["Id"]), "title": row.get("SeriesName") or row.get("Name"), "subtitle": subtitle,
                    "image": self.ref("emby", row["Id"]) if row.get("ImageTags", {}).get("Primary") else None,
                    "link": self.settings.emby_public_url.rstrip("/") + "/web/index.html#!/item?id=" + str(row["Id"])}
            if progress:
                percent = row.get("UserData", {}).get("PlayedPercentage")
                ticks = row.get("UserData", {}).get("PlaybackPositionTicks")
                data["progress"] = min(1, max(0, percent / 100)) if percent is not None else (min(1, max(0, ticks / row["RunTimeTicks"])) if ticks is not None and row.get("RunTimeTicks") else None)
            return data
        return {"continue_watching": [item(r, True) for r in watching["Items"][:8]], "latest": [item(r) for r in latest[:8]]}

    def nav_auth(self):
        salt = secrets.token_hex(8)
        token = hashlib.md5((self.settings.navidrome_password.get_secret_value() + salt).encode(), usedforsecurity=False).hexdigest()
        return {"u": self.settings.navidrome_user, "s": salt, "t": token, "v": "1.16.1", "c": "personal-hub", "f": "json"}

    async def navidrome(self):
        # Subsonic supports POST parameters. Credentials never enter a request URL.
        r = await self.client.post(self.settings.navidrome_url.rstrip("/") + "/rest/getAlbumList2.view",
            data={**self.nav_auth(), "type": "recent", "size": 6})
        r.raise_for_status()
        data = r.json()["subsonic-response"]
        if data["status"] != "ok":
            raise ValueError("subsonic rejected request")
        return {"recent_albums": [{"id": a["id"], "title": a.get("name"), "artist": a.get("artist"),
                 "image": self.ref("navidrome", a.get("coverArt")),
                 "link": self.settings.navidrome_public_url.rstrip("/") + "/app/#/album/" + a["id"] + "/show"} for a in data.get("albumList2", {}).get("album", [])[:6]]}

    async def moviepilot(self):
        r = await self.client.get(self.settings.moviepilot_url.rstrip("/") + "/api/v1/download/",
            headers={"X-API-KEY": self.settings.moviepilot_token.get_secret_value()})
        r.raise_for_status()
        if not isinstance(r.json(), list):
            raise ValueError("invalid download list")
        return {}  # qBittorrent supplies the bounded, deduplicated download rows.

    async def qbittorrent(self):
        url = self.settings.qbittorrent_url.rstrip("/")
        async def login():
            r = await self.qbit.post(url + "/api/v2/auth/login", data={"username": self.settings.qbittorrent_user,
                "password": self.settings.qbittorrent_password.get_secret_value()}, headers={"Referer": url + "/"})
            r.raise_for_status()
            if r.text != "Ok.":
                raise ValueError("download login failed")
        has_login = bool(self.settings.qbittorrent_user and self.settings.qbittorrent_password and self.settings.qbittorrent_password.get_secret_value())
        if has_login and not self.qbit.cookies:
            await login()
        r = await self.qbit.get(url + "/api/v2/torrents/info", params={"filter": "incomplete", "limit": 6, "sort": "added_on", "reverse": "true"})
        if r.status_code == 403 and has_login:
            await login()
            r = await self.qbit.get(url + "/api/v2/torrents/info", params={"filter": "incomplete", "limit": 6, "sort": "added_on", "reverse": "true"})
        r.raise_for_status()
        def state(value):
            if value in ("pausedDL", "stoppedDL"): return "paused"
            if value in ("stalledDL", "error", "missingFiles"): return "stalled"
            if value in ("queuedDL", "checkingDL", "checkingResumeData", "allocating"): return "queued"
            return "downloading"
        return {"downloads": [{"id": t["hash"], "title": t.get("name"), "progress": t.get("progress"), "state": state(t.get("state")),
                 "speed_bps": t.get("dlspeed"), "eta_seconds": t.get("eta") if t.get("eta") is not None and 0 <= t["eta"] < 8640000 else None}
                for t in r.json()[:6]]}

    def adapters(self):
        configured = {"emby": bool(self.settings.emby_token and self.settings.emby_user_id),
                      "navidrome": bool(self.settings.navidrome_user and self.settings.navidrome_password),
                      "moviepilot": bool(self.settings.moviepilot_token),
                      "qbittorrent": self.settings.qbittorrent_user is not None and self.settings.qbittorrent_password is not None}
        return [Adapter(name, name, 30, getattr(self, name) if enabled else None) for name, enabled in configured.items()]
