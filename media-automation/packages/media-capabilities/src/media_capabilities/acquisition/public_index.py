"""Public source contract and Mini4K read-only indexer.

Searching, resolving links and submitting download tasks are separate operations.
Nothing in this module starts a download or writes MoviePilot history.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager, ExitStack
import fcntl
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import parse_qs, quote, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .selection import normalize_title
from .seasons import split_season_title
from .access import download_requires_login, page_access_status
from .evidence import magnet_hash, normalize_magnet
from .torrent_metadata import parse_metadata


class IndexStatus(str, Enum):
    OK = "OK"
    NO_RESULTS = "NO_RESULTS"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CF_CHALLENGE = "CF_CHALLENGE"
    UNAVAILABLE = "UNAVAILABLE"
    PARSE_CHANGED = "PARSE_CHANGED"
    LINK_INVALID = "LINK_INVALID"


class IndexFailure(Exception):
    def __init__(self, status: IndexStatus, reason: str = ""):
        self.status = status
        self.reason = reason or {
            IndexStatus.AUTH_REQUIRED: "Mini4K 服务端登录会话缺失或已失效，请在 NAS 终端运行 mini4k-login",
            IndexStatus.CF_CHALLENGE: "Mini4K Cloudflare 验证尚未完成",
            IndexStatus.UNAVAILABLE: "Mini4K 服务端浏览器访问失败",
        }.get(status, "")
        super().__init__(status.value + ("：" + self.reason if self.reason else ""))


@dataclass(frozen=True)
class MediaQuery:
    title: str
    aliases: tuple[str, ...] = ()
    year: int | None = None
    country: str | None = None
    media_type: str | None = None
    tmdb_id: int | None = None
    imdb_id: str | None = None
    season: int | None = None

    @property
    def names(self) -> tuple[str, ...]:
        names = (self.title, *self.aliases)
        if self.media_type == 'tv' and self.season is not None:
            names = tuple(split_season_title(name)[0] for name in names)
        return tuple(dict.fromkeys(name.strip() for name in names if name.strip()))


@dataclass(frozen=True)
class IndexCandidate:
    candidate_id: str
    source_id: str
    title: str
    media_page_url: str
    resource_page_url: str
    size_bytes: int | None
    media_type: str
    quality_text: str
    link_hint: str
    identity_evidence: str


@dataclass(frozen=True)
class SearchPage:
    status: IndexStatus
    candidates: tuple[IndexCandidate, ...] = ()
    next_cursor: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class DownloadLink:
    kind: str  # magnet, torrent, 115_share, other_cloud_share
    value: str | None = None
    torrent_bytes: bytes | None = None
    info_hash: str | None = None
    files: tuple[str, ...] = ()
    private: bool | None = None
    requires_browser: bool = False


@dataclass(frozen=True)
class ResolvedCandidate:
    status: IndexStatus
    candidate_id: str
    links: tuple[DownloadLink, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class SourceHealth:
    status: IndexStatus
    reason: str = ""
    page_status: IndexStatus | None = None
    resolve_status: IndexStatus | None = None


class PublicIndexer(Protocol):
    def search(self, query: MediaQuery, cursor: str | None = None) -> SearchPage: ...
    def resolve(self, candidate_id: str) -> ResolvedCandidate: ...
    def health(self) -> SourceHealth: ...


class BrowserPage(Protocol):
    def goto(self, url: str) -> str: ...
    def download(self, page_url: str, href: str) -> bytes: ...


class BrowserTransport(Protocol):
    def open(self): ...


class LinuxBrowserTransport:
    """Isolated persistent browser, reusing MoviePilot's CloakBrowser and DISPLAY."""

    def __init__(self, profile_dir: str = "/config/filmwatchlist-mini4k-cloak-browser",
                 executable_path: str | None = None, navigation_lock=None):
        self.profile_dir = Path(profile_dir)
        self.executable_path = executable_path
        self._lock = navigation_lock if navigation_lock is not None else Lock()

    @staticmethod
    def _challenge_click(context, page) -> bool:
        """Locate the actual checkbox through CDP, including closed shadow roots."""
        for frame in page.frames:
            if urlparse(frame.url).hostname != 'challenges.cloudflare.com':
                continue
            cdp = None
            try:
                cdp = context.new_cdp_session(frame)
                nodes = cdp.send('Accessibility.getFullAXTree')['nodes']
                controls = [node for node in nodes
                            if node.get('role', {}).get('value') == 'checkbox'
                            and any(marker in node.get('name', {}).get('value', '').casefold()
                                    for marker in ('human', 'verify', '真人'))
                            and not any(prop.get('name') == 'checked'
                                        and str(prop.get('value', {}).get('value')).lower() == 'true'
                                        for prop in node.get('properties', []))]
                if len(controls) != 1:
                    continue
                quad = cdp.send('DOM.getBoxModel', {
                    'backendNodeId': controls[0]['backendDOMNodeId'],
                })['model']['content']
                offset = frame.frame_element().bounding_box()
                if not offset:
                    continue
                x = sum(quad[::2]) / 4 + offset['x']
                y = sum(quad[1::2]) / 4 + offset['y']
                page.mouse.click(x, y)
                return True
            except Exception:
                # The frame may detach while Cloudflare completes verification.
                continue
            finally:
                if cdp:
                    try:
                        cdp.detach()
                    except Exception:
                        pass
        return False

    @contextmanager
    def profile_lock(self, timeout: float = 10):
        """Coordinate API workers and the one-off login process on this profile."""
        self.profile_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.profile_dir.chmod(0o700)
        fd = os.open(self.profile_dir / '.mini4k-session.lock',
                     os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise IndexFailure(IndexStatus.UNAVAILABLE,
                            'Mini4K 服务端浏览器正在使用中，请稍后重试') from None
                    time.sleep(0.1)
            yield
        finally:
            os.close(fd)

    @contextmanager
    def open_context(self):
        from playwright.sync_api import sync_playwright

        with self._lock, self.profile_lock(), ExitStack() as stack:
            if self.executable_path:
                playwright = stack.enter_context(sync_playwright())
                context = playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir), executable_path=self.executable_path,
                    headless=not bool(os.environ.get('DISPLAY')), accept_downloads=True,
                    viewport={'width': 1280, 'height': 900}, timeout=30000,
                )
            else:
                from cloakbrowser import launch_persistent_context
                context = launch_persistent_context(
                    str(self.profile_dir), headless=not bool(os.environ.get('DISPLAY')),
                    humanize=True, viewport={'width': 1280, 'height': 900},
                    accept_downloads=True, timeout=30000,
                )
            try:
                yield context
            finally:
                context.close()

    def navigate(self, context, page, url: str, *, allow_login: bool = False) -> str:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        try:
            parsed = urlparse(url)
            if parsed.hostname == 'mini4k.io' and parsed.path.startswith('/torrents/'):
                # Search uses the mirror; authenticated downloads use the main site.
                url = urlunparse(parsed._replace(netloc='www.mini4k.com'))
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            deadline = time.monotonic() + 45
            clicks = 0
            challenged = page_access_status(page.content()) == 'CF_CHALLENGE'
            while True:
                html = page.content()
                if page_access_status(html) != 'CF_CHALLENGE' or time.monotonic() >= deadline:
                    break
                if clicks < 2 and self._challenge_click(context, page):
                    clicks += 1
                page.wait_for_timeout(1500)
            status = page_access_status(html)
            if status and not (allow_login and status == 'AUTH_REQUIRED'):
                raise IndexFailure(IndexStatus(status))
            # Judge a completed challenge by its final page, not the initial 403.
            if challenged or (response and response.url != page.url):
                response = None
            if response and response.status == 401:
                raise IndexFailure(IndexStatus.AUTH_REQUIRED)
            if response and response.status == 403:
                raise IndexFailure(IndexStatus.CF_CHALLENGE
                    if response.headers.get('cf-mitigated') == 'challenge' else IndexStatus.UNAVAILABLE)
            return html
        except PlaywrightTimeout as exc:
            raise IndexFailure(IndexStatus.UNAVAILABLE, 'Mini4K 服务端页面访问超时') from exc

    @contextmanager
    def open(self):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        with self.open_context() as context:
            page = context.pages[0] if context.pages else context.new_page()
            transport = self

            class Session:
                def goto(self, url: str) -> str:
                    return transport.navigate(context, page, url)

                def download(self, page_url: str, href: str) -> bytes:
                    try:
                        if urlparse(page.url).path != urlparse(page_url).path:
                            self.goto(page_url)
                        link = next((item for item in page.locator("a[href]").all()
                                     if item.get_attribute("href") == href), None)
                        if link is None:
                            raise IndexFailure(IndexStatus.LINK_INVALID)
                        with page.expect_download(timeout=20000) as event:
                            link.click()
                        path = event.value.path()
                        if not path or Path(path).stat().st_size > 10 * 1024 * 1024:
                            raise IndexFailure(IndexStatus.LINK_INVALID)
                        return Path(path).read_bytes()
                    except PlaywrightTimeout as exc:
                        status = page_access_status(page.content())
                        if status:
                            raise IndexFailure(IndexStatus(status)) from exc
                        raise IndexFailure(IndexStatus.LINK_INVALID) from exc

            yield Session()


SIZE_RE = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*(TB|GB|MB)")
YEAR_RE = re.compile(r"\((19\d{2}|20\d{2})(?:\s*[-–—]\s*(?:19|20)\d{2})?\)")
MEDIA_RE = re.compile(r"^/(movies|shows)/\d+(?:/)?$")
COUNTRY_ALIASES = {
    "美国": ("美国", "usa", "united states"),
    "法国": ("法国", "france"),
}
OTHER_CLOUD_HOSTS = {"pan.baidu.com", "pan.quark.cn", "www.alipan.com", "pan.xunlei.com"}


def share_kind(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    if parsed.hostname in ("115.com", "www.115.com", "pan.115.com") and parsed.path.startswith("/s/"):
        return "115_share"
    if parsed.hostname in OTHER_CLOUD_HOSTS:
        return "other_cloud_share"
    return None


def parse_torrent(content: bytes) -> tuple[str, tuple[str, ...], bool]:
    """Validate bencoded torrent metadata before exposing its info hash or files."""
    metadata = parse_metadata(content)
    return metadata.info_hash, tuple(name for name, _ in metadata.files), metadata.private



class Mini4KIndexer:
    source_id = "mini4k"
    default_base_url = "https://mini4k.io"

    def __init__(self, browser: BrowserTransport | None = None,
                 base_url: str = default_base_url):
        parsed = urlparse(base_url.rstrip("/"))
        if parsed.scheme != "https" or parsed.hostname not in ("www.mini4k.com", "mini4k.com", "mini4k.io") \
                or parsed.path or parsed.query or parsed.fragment or parsed.port:
            raise ValueError("Mini4K 域名不在允许列表中")
        self.base_url = base_url.rstrip("/")
        self.browser = browser or LinuxBrowserTransport()
        self._last_resolve_status = None
        self._last_resolve_reason = ""
        self._detail_cache = {}
        self._detail_lock = Lock()

    @staticmethod
    def _candidate_id(resource_url: str, direct_link: str | None = None) -> str:
        parsed = urlparse(resource_url)
        match = re.fullmatch(r'/(movies|shows|torrents)/(\d+)/?', parsed.path)
        if parsed.scheme != 'https' or parsed.hostname not in (
                'www.mini4k.com', 'mini4k.com', 'mini4k.io') or not match:
            raise ValueError('候选资源地址无效')
        # Only public page identity and a one-way link selector cross the state boundary.
        selector = Mini4KIndexer._link_selector(direct_link) if direct_link else '-'
        return f'mini4k:v2:{parsed.hostname}:{match[1]}:{match[2]}:{selector}'

    @staticmethod
    def _link_selector(link: str) -> str:
        if link.startswith('magnet:?'):
            try:
                identity = 'magnet:' + magnet_hash(link)
            except ValueError:
                identity = normalize_magnet(link)
        else:
            parsed = urlparse(link)
            # Extraction codes can rotate without changing the candidate's identity.
            identity = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
        return hashlib.sha256(identity.encode()).hexdigest()

    @classmethod
    def comparable_candidate_id(cls, candidate_id: str) -> str:
        """Compare historical IDs to new search results without rewriting stored keys."""
        if not candidate_id.startswith('mini4k:') or candidate_id.startswith('mini4k:v2:'):
            return candidate_id
        try:
            encoded = candidate_id.removeprefix('mini4k:')
            resource, link = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
            return cls._candidate_id(resource, link)
        except (ValueError, TypeError, AttributeError):
            return candidate_id

    def _candidate_target(self, candidate_id: str) -> tuple[str, str | None] | None:
        if not candidate_id.startswith("mini4k:") or len(candidate_id) > 4096:
            return None
        if candidate_id.startswith('mini4k:v2:'):
            match = re.fullmatch(
                r'mini4k:v2:(www\.mini4k\.com|mini4k\.com|mini4k\.io):'
                r'(movies|shows|torrents):(\d+):(-|[a-f0-9]{64})', candidate_id)
            if not match:
                return None
            return (f'https://{match[1]}/{match[2]}/{match[3]}',
                    'sha256:' + match[4] if match[4] != '-' else None)
        # Existing records remain readable; never rewrite their IDs or lose in-flight tasks.
        try:
            encoded = candidate_id.removeprefix("mini4k:")
            resource_url, direct_link = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        except (ValueError, TypeError):
            return None
        if not isinstance(resource_url, str) or self._site_url(resource_url) != resource_url:
            return None
        if not urlparse(resource_url).path.startswith(("/movies/", "/shows/", "/torrents/")):
            return None
        if direct_link is not None and not isinstance(direct_link, str):
            return None
        if direct_link and not (share_kind(direct_link) or direct_link.startswith("magnet:?")):
            return None
        return resource_url, direct_link

    def _site_url(self, href: str) -> str | None:
        url = urljoin(self.base_url, href)
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ("www.mini4k.com", "mini4k.com", "mini4k.io"):
            return None
        return url

    @staticmethod
    def _size(text: str) -> int | None:
        match = SIZE_RE.search(text)
        if not match:
            return None
        return int(float(match.group(1)) * {"MB": 1024**2, "GB": 1024**3, "TB": 1024**4}[match.group(2).upper()])

    @staticmethod
    def _page_status(html: str) -> IndexStatus | None:
        status = page_access_status(html)
        return IndexStatus(status) if status else None

    def _next_search_url(self, soup: BeautifulSoup, term: str, current_url: str) -> str | None:
        for link in soup.select("a[href]"):
            label = link.get_text(" ", strip=True).casefold()
            if "next" not in link.get("rel", []) and label not in ("下一页", "下页", "next", "›", "»"):
                continue
            url = self._site_url(link.get("href", ""))
            if url and url != current_url and urlparse(url).path == "/search" \
                    and parse_qs(urlparse(url).query).get("text") == [term]:
                return url
        return None

    @staticmethod
    def _identity_matches(soup: BeautifulSoup, url: str, query: MediaQuery) -> tuple[bool, str]:
        heading = soup.find("h1")
        if not heading:
            return False, "缺少影片标题"
        heading_text = heading.get_text(" ", strip=True)
        year_node = heading.select_one(".node-year")
        year_match = YEAR_RE.search(year_node.get_text(" ", strip=True) if year_node else heading_text)
        if query.year and (not year_match or int(year_match.group(1)) != query.year):
            return False, "年份不符或未知"
        page_type = "movie" if "/movies/" in url else "tv"
        if query.media_type and page_type != query.media_type:
            return False, "媒体类型不符"
        body_text = soup.get_text(" ", strip=True)
        heading_at = body_text.find(heading_text)
        header_text = body_text[max(0, heading_at):max(0, heading_at) + 350]
        # Current TV headings mix both names, a year range, and a live season badge.
        title_nodes = heading.select('.ch-title, .en-title')
        heading_title = re.sub(r'\((?:19|20)\d{2}(?:\s*[-–—]\s*(?:19|20)\d{2})?\)', '', heading_text).strip()
        title_keys = {normalize_title(name) for name in query.names}
        title_parts = [node.get_text(' ', strip=True) for node in title_nodes] if title_nodes else \
            re.split(r"\s*[/|｜]\s*", heading_title)
        title_parts.extend(name for part in tuple(title_parts)
                           for name in re.split(r"(?<=[\u4e00-\u9fff])\s+(?=[A-Za-z])", part))
        if not any(normalize_title(part) in title_keys for part in title_parts):
            return False, "片名不符"
        if query.tmdb_id:
            tmdb_links = [urlparse(a.get("href", "")) for a in soup.select("a[href*='themoviedb.org']")]
            tmdb_ids = {int(match.group(1)) for parsed in tmdb_links
                        if (match := re.search(r"/(?:movie|tv)/(\d+)", parsed.path))}
            if tmdb_ids and query.tmdb_id not in tmdb_ids:
                return False, "TMDb ID 不符"
        if query.imdb_id:
            imdb_ids = {match.group(0) for a in soup.select("a[href*='imdb.com/title/']")
                        if (match := re.search(r"tt\d+", a.get("href", "")))}
            if imdb_ids and query.imdb_id not in imdb_ids:
                return False, "IMDb ID 不符"
        if query.country:
            aliases = COUNTRY_ALIASES.get(query.country, (query.country,))
            if not any(alias.casefold() in header_text.casefold() for alias in aliases):
                return False, "国家未知或不符"
        return True, f"标题、年份、类型、国家已按可用字段核对：{heading_text}"

    def search(self, query: MediaQuery, cursor: str | None = None) -> SearchPage:
        return self._search_impl(query, cursor, self.browser)

    def _search_impl(self, query: MediaQuery, cursor: str | None,
                     browser: BrowserTransport) -> SearchPage:
        if not query.names:
            return SearchPage(IndexStatus.NO_RESULTS, reason="片名为空")
        try:
            state = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else {"term": 0}
            start = int(state["term"])
            search_url = state.get("url") or f"{self.base_url}/search?text={quote(query.names[start])}"
        except (ValueError, KeyError, IndexError, TypeError):
            return SearchPage(IndexStatus.PARSE_CHANGED, reason="无效的搜索游标")
        if start < 0 or start >= len(query.names):
            return SearchPage(IndexStatus.PARSE_CHANGED, reason="搜索游标越界")
        term = query.names[start]
        if not self._site_url(search_url) or urlparse(search_url).path != "/search" \
                or parse_qs(urlparse(search_url).query).get("text") != [term]:
            return SearchPage(IndexStatus.PARSE_CHANGED, reason="搜索游标地址无效")
        candidates: list[IndexCandidate] = []
        unrecognized_rows = False
        try:
            with browser.open() as page:
                html = page.goto(search_url)
                status = self._page_status(html)
                if status:
                    return SearchPage(status)
                soup = BeautifulSoup(html, "html.parser")
                next_url = self._next_search_url(soup, term, search_url)
                media_urls = []
                recognized_results = False
                for link in soup.select("a[href]"):
                    url = self._site_url(link.get("href", ""))
                    if not url or not MEDIA_RE.match(urlparse(url).path) or url in media_urls:
                        continue
                    recognized_results = True
                    path_type = "movie" if "/movies/" in urlparse(url).path else "tv"
                    if query.media_type and query.media_type != path_type:
                        continue
                    card = link.find_parent("div", class_="content")
                    year_node = card.select_one(".meta-item.year") if card else None
                    if query.year and year_node:
                        listed_year = re.search(r"(?:19|20)\d{2}", year_node.get_text(" ", strip=True))
                        if listed_year and int(listed_year.group(0)) != query.year:
                            continue
                    media_urls.append(url)
                if not media_urls and not recognized_results:
                    page_text = soup.get_text(" ", strip=True).casefold()
                    empty_markers = ("没有搜索结果", "没有找到", "暂无结果", "无搜索结果",
                                     "无任何结果", "no results")
                    count = soup.select_one('.search-count-label')
                    explicit_zero = count and re.fullmatch(r'0\s*个结果', count.get_text(' ', strip=True))
                    if not explicit_zero and not any(marker in page_text for marker in empty_markers):
                        return SearchPage(IndexStatus.PARSE_CHANGED, reason="搜索页没有可识别的结果或空结果标记")
                for media_url in media_urls:
                    with self._detail_lock:
                        cached = self._detail_cache.get(media_url)
                    detail_html = cached[1] if cached and cached[0] > time.monotonic() else page.goto(media_url)
                    status = self._page_status(detail_html)
                    if status:
                        return SearchPage(status)
                    with self._detail_lock:
                        if len(self._detail_cache) >= 128:
                            self._detail_cache.pop(next(iter(self._detail_cache)))
                        self._detail_cache[media_url] = (time.monotonic() + 300, detail_html)
                    detail = BeautifulSoup(detail_html, "html.parser")
                    matched, evidence = self._identity_matches(detail, media_url, query)
                    if not matched:
                        continue
                    for row in detail.select("table tr"):
                        torrent_link = None
                        direct_link = None
                        for anchor in row.select("a[href]"):
                            href = anchor.get("href", "").strip()
                            site_url = self._site_url(href)
                            if site_url and urlparse(site_url).path.startswith("/torrents/"):
                                torrent_link = anchor
                                break
                            if share_kind(href) or href.startswith("magnet:?"):
                                direct_link = href
                        if not torrent_link and not direct_link:
                            if row.select("a[href]"):
                                unrecognized_rows = True
                            continue
                        resource_url = self._site_url(torrent_link.get("href", "")) if torrent_link else media_url
                        title = (torrent_link.get_text(" ", strip=True) if torrent_link else
                                 row.get_text(" ", strip=True))
                        if not title:
                            continue
                        row_text = row.get_text(" ", strip=True)
                        if query.season is not None and '/shows/' in media_url:
                            try:
                                _, resource_season = split_season_title(row_text)
                            except ValueError:
                                continue
                            if resource_season is not None and resource_season != query.season:
                                continue
                        candidate_id = self._candidate_id(resource_url, direct_link)
                        item = IndexCandidate(
                            candidate_id=candidate_id, source_id=self.source_id, title=title,
                            media_page_url=media_url, resource_page_url=resource_url,
                            size_bytes=self._size(row_text),
                            media_type="movie" if "/movies/" in media_url else "tv",
                            quality_text=row_text,
                            link_hint=(share_kind(direct_link) or "magnet") if direct_link else "unresolved",
                            identity_evidence=evidence,
                        )
                        candidates.append(item)
        except IndexFailure as exc:
            return SearchPage(exc.status, reason=exc.reason)
        except Exception:
            return SearchPage(IndexStatus.UNAVAILABLE, reason="浏览器访问失败")
        if not candidates and unrecognized_rows:
            return SearchPage(IndexStatus.PARSE_CHANGED, reason="资源表含有未识别的链接结构")
        next_state = {"term": start, "url": next_url} if next_url else \
            {"term": start + 1} if start + 1 < len(query.names) else None
        next_cursor = base64.urlsafe_b64encode(json.dumps(next_state).encode()).decode() if next_state else None
        return SearchPage(IndexStatus.OK if candidates else IndexStatus.NO_RESULTS,
                          tuple(dict.fromkeys(candidates)), next_cursor)

    def resolve(self, candidate_id: str) -> ResolvedCandidate:
        result = self._resolve_impl(candidate_id, self.browser)
        self._last_resolve_status = result.status
        self._last_resolve_reason = result.reason
        return result

    def _resolve_impl(self, candidate_id: str,
                      browser: BrowserTransport) -> ResolvedCandidate:
        target = self._candidate_target(candidate_id)
        if target is None:
            return ResolvedCandidate(IndexStatus.LINK_INVALID, candidate_id, reason="候选 ID 无效")
        resource_url, direct_link = target
        links: list[DownloadLink] = []
        download_failure = None
        login_download = False
        try:
            with browser.open() as page:
                html = page.goto(resource_url)
                status = self._page_status(html)
                if status:
                    return ResolvedCandidate(status, candidate_id, reason=IndexFailure(status).reason)
                soup = BeautifulSoup(html, "html.parser")
                login_download = download_requires_login(html)
                if direct_link and direct_link.startswith('sha256:'):
                    selector = direct_link.removeprefix('sha256:')
                    direct_link = next((href for anchor in soup.select('a[href]')
                                        if (href := anchor.get('href', '').strip())
                                        and (share_kind(href) or href.startswith('magnet:?'))
                                        and self._link_selector(href) == selector), None)
                    if direct_link is None:
                        return ResolvedCandidate(
                            IndexStatus.AUTH_REQUIRED if login_download else IndexStatus.LINK_INVALID,
                            candidate_id, reason='资源页不再包含该候选链接')
                def same_link(href):
                    if direct_link and direct_link.startswith('magnet:?') and href.startswith('magnet:?'):
                        return normalize_magnet(href) == normalize_magnet(direct_link)
                    return href == direct_link

                if direct_link and not any(same_link(anchor.get("href", "").strip())
                                           for anchor in soup.select("a[href]")):
                    if login_download:
                        return ResolvedCandidate(IndexStatus.AUTH_REQUIRED, candidate_id,
                                                 reason="资源下载按钮要求登录 Mini4K")
                    return ResolvedCandidate(IndexStatus.LINK_INVALID, candidate_id,
                                             reason="资源页不再包含该下载链接")
                if direct_link:
                    kind = share_kind(direct_link)
                    if kind:
                        return ResolvedCandidate(IndexStatus.OK, candidate_id,
                                                 (DownloadLink(kind, value=direct_link),))
                    try:
                        info_hash = magnet_hash(direct_link)
                        return ResolvedCandidate(IndexStatus.OK, candidate_id,
                                                 (DownloadLink("magnet", value=normalize_magnet(direct_link),
                                                               info_hash=info_hash),))
                    except ValueError:
                        pass
                    return ResolvedCandidate(IndexStatus.LINK_INVALID, candidate_id,
                                             reason="磁力链接缺少有效 info-hash")
                downloaded_torrent = False
                for anchor in soup.select("a[href]"):
                    href = anchor.get("href", "").strip()
                    if href.startswith("magnet:?"):
                        try:
                            info_hash = magnet_hash(href)
                            links.append(DownloadLink("magnet", value=normalize_magnet(href),
                                                      info_hash=info_hash, private=None))
                        except ValueError:
                            continue
                    elif not downloaded_torrent and ".torrent" in urlparse(href).path.lower():
                        url = self._site_url(href)
                        if not url:
                            continue
                        try:
                            content = page.download(resource_url, href)
                            info_hash, files, private = parse_torrent(content)
                            links.append(DownloadLink("torrent", torrent_bytes=content,
                                                      info_hash=info_hash, files=files,
                                                      private=private, requires_browser=True))
                            downloaded_torrent = True
                        except IndexFailure as exc:
                            download_failure = exc.status
                            continue
                        except ValueError:
                            continue
                for match in re.finditer(r"https://(?:www\.)?(?:115\.com|pan\.115\.com)/s/[\w-]+", html):
                    links.append(DownloadLink("115_share", value=match.group(0)))
                for anchor in soup.select("a[href]"):
                    href = anchor.get("href", "")
                    kind = share_kind(href)
                    if kind:
                        links.append(DownloadLink(kind, value=href))
        except IndexFailure as exc:
            return ResolvedCandidate(exc.status, candidate_id, reason=exc.reason)
        except Exception:
            return ResolvedCandidate(IndexStatus.UNAVAILABLE, candidate_id, reason="资源页访问失败")
        unique = tuple({(link.kind, link.info_hash or link.value): link for link in links}.values())
        if not unique and (download_failure or login_download):
            return ResolvedCandidate(download_failure or IndexStatus.AUTH_REQUIRED, candidate_id,
                                     reason="下载会话被拦截" if download_failure else
                                     IndexFailure(IndexStatus.AUTH_REQUIRED).reason)
        return ResolvedCandidate(IndexStatus.OK if unique else IndexStatus.LINK_INVALID,
                                 candidate_id, unique,
                                 "" if unique else "没有取得真实磁力、种子文件或网盘分享链接")

    def health(self) -> SourceHealth:
        reason = '页面可访问；尚未检查资源下载权限'
        try:
            with self.browser.open() as page:
                html = page.goto(self.base_url)
                status = self._page_status(html) or IndexStatus.OK
        except IndexFailure as exc:
            status = exc.status
            reason = exc.reason
        except Exception:
            status = IndexStatus.UNAVAILABLE
            reason = '浏览器访问失败'
        last = self._last_resolve_status
        overall = status
        if status == IndexStatus.OK and last is not None:
            reason = f'页面访问正常；最近一次资源解析：{last.value}'
            if self._last_resolve_reason:
                reason += '；' + self._last_resolve_reason
            if last in (IndexStatus.AUTH_REQUIRED, IndexStatus.CF_CHALLENGE, IndexStatus.UNAVAILABLE):
                overall = last
        return SourceHealth(overall, reason, page_status=status, resolve_status=last)
