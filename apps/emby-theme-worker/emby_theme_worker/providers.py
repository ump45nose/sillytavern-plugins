from __future__ import annotations

import json
import re
from html import unescape
from urllib.parse import quote, urljoin

import httpx
from .db import StateDB
from .models import Candidate, MediaItem
from .scoring import normalize
from .ytdlp_runner import search as ytdlp_search


UA = "emby-theme-worker/0.1 (+private-home-instance)"


class ProviderBlocked(RuntimeError):
    pass


class ProviderParserError(RuntimeError):
    pass


class Providers:
    def __init__(
        self,
        enabled: list[str],
        timeout: int,
        db: StateDB,
        cookies: dict[str, str],
        ytdlp_search_timeout: int = 60,
    ):
        self.enabled = set(enabled)
        self.timeout = timeout
        self.db = db
        self.cookies = cookies
        self.ytdlp_search_timeout = ytdlp_search_timeout
        self.http = httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})

    def close(self) -> None:
        self.http.close()

    def _enabled(self, name: str) -> bool:
        return name in self.enabled and self.db.provider_available("resolver", name)

    def animethemes(self, item: MediaItem) -> Candidate | None:
        query_text = item.original_title or item.name
        query = """
        query($search: String!) {
          search(search: $search, first: 8) {
            anime {
              year slug title { romaji english native }
              animethemes { type sequence slug animethemeentries { videos { nodes { link audio { link } } } } }
            }
          }
        }
        """
        payload = self.http.post(
            "https://graphql.animethemes.moe",
            json={"query": query, "variables": {"search": query_text}},
        ).raise_for_status().json()
        if payload.get("errors"):
            raise RuntimeError("AnimeThemes GraphQL error")
        expected = {normalize(item.name), normalize(item.original_title)} - {""}
        for anime in payload.get("data", {}).get("search", {}).get("anime", []):
            titles = anime.get("title") or {}
            actual = {normalize(titles.get(key)) for key in ("romaji", "english", "native")} - {""}
            if expected.isdisjoint(actual):
                continue
            if not item.year or not anime.get('year') or int(item.year) != int(anime['year']):
                continue
            themes = sorted(
                (theme for theme in anime.get("animethemes", []) if theme.get("type") == "OP"),
                key=lambda theme: int(theme.get("sequence") or 999),
            )
            for theme in themes:
                if int(theme.get("sequence") or 0) != 1:
                    continue
                for entry in theme.get("animethemeentries", []):
                    for video in (entry.get("videos") or {}).get("nodes", []):
                        source = (video.get("audio") or {}).get("link") or video.get("link")
                        if source:
                            return Candidate("animethemes", f"{query_text} OP1", source, exact=True, year=anime.get("year"), transport="direct_http", metadata={'identity_kind':'strict_title_year','anime_slug':anime.get('slug')})
        return None

    def themerrdb(self, item: MediaItem) -> Candidate | None:
        tmdb = item.provider_ids.get("Tmdb") or item.provider_ids.get("TMDb") or item.provider_ids.get("TheMovieDb")
        media = "movies" if item.item_type == "Movie" else "tv_shows"
        imdb = next((v for k, v in item.provider_ids.items() if k.casefold() == "imdb"), None)
        for namespace, identity in (("themoviedb", tmdb), ("imdb", imdb)):
            if not identity:
                continue
            url = f"https://app.lizardbyte.dev/ThemerrDB/{media}/{namespace}/{quote(identity)}.json"
            response = self.http.get(url)
            if response.status_code == 404:
                continue
            payload = response.raise_for_status().json()
            source = payload.get("youtube_theme_url")
            if source:
                return Candidate("themerrdb", f"{item.original_title or item.name} main theme", source,
                                 exact=True, year=item.year, media_type=item.item_type,
                                 metadata={"identity_namespace": namespace, "identity": identity}, transport="youtube")
        return None

    def plex_tv(self, item: MediaItem) -> Candidate | None:
        tvdb = item.provider_ids.get("Tvdb") or item.provider_ids.get("TVDb")
        if not tvdb:
            return None
        url = f"https://tvthemes.plexapp.com/{quote(tvdb)}.mp3"
        response = self.http.head(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if "audio" not in response.headers.get("content-type", ""):
            return None
        return Candidate("plex_tv", f"{item.original_title or item.name} TV theme", url, exact=True, year=item.year, media_type="Series", transport="direct_http", metadata={'identity_namespace':'tvdb','identity':tvdb})

    def _query(self, item: MediaItem) -> str:
        if item.search_text:
            return item.search_text
        title = item.original_title or item.name
        year = f" {item.year}" if item.year else ""
        intent = " opening theme OP1" if item.is_anime else " main theme soundtrack"
        return f"{title}{year}{intent}"

    def archive(self, item: MediaItem) -> list[Candidate]:
        title = (item.original_title or item.name).replace('"', '')
        intent = 'theme OR soundtrack OR opening'
        if item.search_text:
            remainder = normalize(item.search_text)
            for name in (item.original_title,item.name,*item.aliases):
                if name:remainder=remainder.replace(normalize(name),' ')
            words = [w for w in remainder.split() if not w.isdigit() and w in {'theme','main','title','titles','music','soundtrack','opening','ending','end','credits'}]
            if words:intent=' AND '.join(words)
        query = f'title:("{title}") AND ({intent}) AND mediatype:audio'
        params = [("q", query), ("output", "json"), ("rows", "10")]
        for field in ("identifier", "title", "year", "licenseurl"):
            params.append(("fl[]", field))
        payload = self.http.get("https://archive.org/advancedsearch.php", params=params).raise_for_status().json()
        found: list[Candidate] = []
        for doc in payload.get("response", {}).get("docs", []):
            license_url = str(doc.get("licenseurl") or "").casefold()
            if not any(term in license_url for term in ("creativecommons.org", "publicdomain")):
                continue
            identifier = doc.get("identifier")
            metadata = self.http.get(f"https://archive.org/metadata/{quote(str(identifier))}").raise_for_status().json()
            md = metadata.get("metadata", {})
            rights = " ".join(str(md.get(k) or "") for k in ("licenseurl", "rights")).casefold()
            if not any(term in rights for term in ("creativecommons.org", "public domain", "publicdomain")):
                continue
            media_file = next(
                (f for f in metadata.get("files", []) if str(f.get("name", "")).lower().endswith((".mp3", ".ogg", ".flac")) and f.get("source") == "original"),
                None,
            )
            if not media_file:
                continue
            source = f"https://archive.org/download/{quote(str(identifier))}/{quote(str(media_file['name']))}"
            found.append(Candidate("archive", str(doc.get("title") or identifier), source, year=_year(doc.get("year")), metadata={"license": rights[:200]}, transport="direct_http"))
        return found

    def televisiontunes(self, item: MediaItem) -> list[Candidate]:
        title = item.original_title or item.name
        query = item.search_text or title
        response = self.http.get("https://www.televisiontunes.co.uk/", params={"s": query})
        self._usable_html(response)
        canonical = lambda value: re.sub(r'^(the|a|an)\s+', '', normalize(value))
        expected = canonical(title)
        links: list[str] = []
        for href, label in re.findall(r'href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', response.text, re.I | re.S):
            url = urljoin(str(response.url), href)
            if "televisiontunes.co.uk/" not in url or "/themes/" in url or "/search/" in url:
                continue
            label_text = canonical(re.sub(r"<[^>]+>", " ", unescape(label)))
            slug_text = canonical(url.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
            if expected and expected in {label_text, slug_text} and url not in links:
                links.append(url)
        found: list[Candidate] = []
        for detail_url in links[:5]:
            detail = self.http.get(detail_url)
            self._usable_html(detail)
            audio = re.findall(r'contentUrl["\']?\s*:\s*["\']([^"\']+)', detail.text, re.I)
            if not audio:
                audio = re.findall(r'<source[^>]+src=["\']([^"\']+)', detail.text, re.I)
            for source in audio[:1]:
                found.append(Candidate(
                    "televisiontunes", f"{query} television theme", urljoin(str(detail.url), unescape(source)),
                    exact=False, media_type="Series", transport="direct_http",
                    metadata={"curated_source": True},
                ))
        if links and not found:
            raise ProviderParserError("matching detail page contained no audio URL")
        return found

    @staticmethod
    def _usable_html(response: httpx.Response) -> None:
        if response.status_code in {401, 403, 429}:
            raise ProviderBlocked(f"HTTP {response.status_code}")
        response.raise_for_status()
        lowered = response.text.casefold()
        if "just a moment" in lowered or "cf-chl-" in lowered:
            raise ProviderBlocked("anti-bot challenge")

    def tunefind(self, item: MediaItem) -> list[Candidate]:
        raise ProviderBlocked("official Tunefind API credentials are required")

    def _ytdlp_search(self, provider: str, prefix: str, item: MediaItem) -> list[Candidate]:
        cookie = self.cookies.get(provider)
        info = ytdlp_search(
            f"{prefix}10:{self._query(item)}",
            cookie_file=cookie,
            socket_timeout_seconds=self.timeout,
            hard_timeout_seconds=self.ytdlp_search_timeout,
        )
        candidates: list[Candidate] = []
        for entry in (info or {}).get("entries") or []:
            if not entry:
                continue
            source = entry.get("webpage_url") or entry.get("url")
            if source and not str(source).startswith("http") and provider == "youtube":
                source = f"https://www.youtube.com/watch?v={source}"
            if source:
                candidates.append(Candidate(
                    provider, entry.get("title") or "", str(source),
                    duration=entry.get("duration"), metadata={"channel": entry.get("channel") or entry.get("uploader") or "", "channel_verified": bool(entry.get("channel_is_verified"))}, transport=provider,
                ))
        return candidates

    def youtube(self, item: MediaItem) -> list[Candidate]:
        return self._ytdlp_search("youtube", "ytsearch", item)

    def bilibili(self, item: MediaItem) -> list[Candidate]:
        try:
            found=self._ytdlp_search("bilibili", "bilisearch", item)
            usable=[candidate for candidate in found if candidate.title.strip()]
            if usable:return usable
        except Exception:
            pass
        # Flat Bili playlists can contain IDs but no titles; these are handles,
        # not rankable candidates. Resolve metadata through the search API.
        payload = self.http.get("https://api.bilibili.com/x/web-interface/search/type", params={"search_type": "video", "keyword": self._query(item), "page": 1}).raise_for_status().json()
        if payload.get('code') not in (None,0):
            raise ProviderBlocked('Bilibili search API rejected the request')
        return [
            Candidate("bilibili", unescape(re.sub(r"<[^>]+>", "", row.get("title") or "")), f"https://www.bilibili.com/video/{row['bvid']}", duration=_duration(row.get("duration")), transport="bilibili")
            for row in payload.get("data", {}).get("result", [])[:10] if row.get("bvid") and row.get('title')
        ]

    def netease(self, item: MediaItem) -> list[Candidate]:
        payload = self.http.get("https://music.163.com/api/search/get", params={"s": self._query(item), "type": 1, "limit": 10, "offset": 0}).raise_for_status().json()
        rows = payload.get("result", {}).get("songs", [])
        return [
            Candidate(
                "netease", f"{row.get('name','')} - {'/'.join(a.get('name','') for a in row.get('artists',[]))}",
                f"https://music.163.com/#/song?id={row.get('id')}",
                duration=(row.get("duration") or 0) / 1000,
                metadata={"catalog_id": str(row.get("id", "")), "album_title": (row.get("album") or {}).get("name", ""), "transport": "netease/yt-dlp"}, transport="netease",
            )
            for row in rows if row.get("id")
        ]

    def qqmusic(self, item: MediaItem) -> list[Candidate]:
        params = {"w": self._query(item), "format": "json", "p": 1, "n": 10}
        payload = self.http.get("https://c.y.qq.com/soso/fcgi-bin/client_search_cp", params=params, headers={"Referer": "https://y.qq.com/"}).raise_for_status().json()
        rows = payload.get("data", {}).get("song", {}).get("list", [])
        return [
            Candidate(
                "qqmusic", f"{row.get('songname','')} - {'/'.join(a.get('name','') for a in row.get('singer',[]))}",
                f"https://y.qq.com/n/ryqq/songDetail/{row.get('songmid')}",
                duration=row.get("interval"),
                metadata={"catalog_id": row.get("songmid"), "album_title": row.get("albumname", ""), "transport": "qqmusic/yt-dlp"}, transport="qqmusic",
            )
            for row in rows if row.get("songmid")
        ]


def _year(value: object) -> int | None:
    match = re.search(r"\d{4}", str(value or ""))
    return int(match.group()) if match else None


def _duration(value: object) -> float | None:
    if not value:
        return None
    parts = str(value).split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return float(value)
    except ValueError:
        return None
