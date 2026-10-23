"""Read a Bilibili favorite folder as film leads, without downloading videos."""

from __future__ import annotations

from datetime import date
import logging
import re
import unicodedata
import time

import requests

from .bili_credentials import read_bili_sync_credential
from .common import SyncError
from .config import proxy_url


TITLE = re.compile(r"《([^《》]{1,120})》")
DATE_LABEL = re.compile(r"(?:上映日期|上映时间|首播日期|首播|播出周期|播出日期|上线时间)\s*[:：]\s*")
FULL_DATE = re.compile(
    r"(?<!\d)(?P<year>19\d{2}|20\d{2})\s*"
    r"(?:年\s*(?P<month_cn>\d{1,2})\s*月\s*(?P<day_cn>\d{1,2})\s*日?"
    r"|[-/.]\s*(?P<month_num>\d{1,2})\s*[-/.]\s*(?P<day_num>\d{1,2}))(?!\d)"
)
YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
COUNTRIES = tuple(sorted((
    "中国香港", "中国澳门", "中国台湾", "中国大陆", "克罗地亚", "沙特阿拉伯", "阿联酋",
    "新西兰", "澳大利亚", "俄罗斯", "乌克兰", "白俄罗斯", "哈萨克斯坦", "乌兹别克斯坦",
    "巴基斯坦", "孟加拉国", "斯里兰卡", "印度尼西亚", "马来西亚", "新加坡",
    "菲律宾", "柬埔寨", "泰国", "越南", "缅甸", "尼泊尔", "蒙古", "印度",
    "卡塔尔", "土耳其", "伊朗", "伊拉克", "以色列", "埃及", "南非", "尼日利亚",
    "摩洛哥", "阿尔及利亚", "肯尼亚", "墨西哥", "阿根廷", "巴西", "智利",
    "哥伦比亚", "加拿大", "美国", "英国", "爱尔兰", "法国", "德国", "意大利",
    "西班牙", "葡萄牙", "荷兰", "比利时", "瑞士", "奥地利", "瑞典", "挪威",
    "丹麦", "芬兰", "冰岛", "波兰", "捷克", "匈牙利", "罗马尼亚", "希腊",
    "塞尔维亚", "斯洛文尼亚", "波黑", "保加利亚", "日本", "韩国", "朝鲜",
    "中国",
), key=len, reverse=True))


def film_titles(video_title: str) -> list[tuple[str, str]]:
    result = []
    seen = set()
    for raw in TITLE.findall(video_title):
        title = " ".join(unicodedata.normalize("NFKC", raw).strip().split())
        key = title.casefold()
        if title and key not in seen:
            result.append((title, key))
            seen.add(key)
    return result


def film_season(title: str, source_titles: list[str]) -> tuple[int | None, str]:
    """Recover only season labels inside this title or immediately beside its 《》."""
    label = re.compile(r"第\s*([0-9一二三四五六七八九十百零〇两]+)\s*季|"
                       r"(?<![A-Za-z0-9])(?:season\s*|s)([0-9]{1,3})(?![0-9]|[Ee][0-9])", re.I)
    def number(value):
        if value.isdecimal():
            return int(value)
        digits = {c: n for n, c in enumerate('零一二三四五六七八九')}
        total = current = 0
        for char in value.replace('两', '二').replace('〇', '零'):
            if char in digits:
                current = digits[char]
            elif char in ('十', '百'):
                total += (current or 1) * (10 if char == '十' else 100)
                current = 0
        return total + current
    normalized = unicodedata.normalize('NFKC', title).strip()
    labels = list(label.finditer(normalized))
    for source in source_titles:
        source = unicodedata.normalize('NFKC', source)
        for match in TITLE.finditer(source):
            if match[1].strip().casefold() != normalized.casefold():
                continue
            suffix = source[match.end():].lstrip()
            prefix = source[:match.start()].rstrip()
            after = label.match(suffix)
            before = next((m for m in label.finditer(prefix) if m.end() == len(prefix)), None)
            labels.extend(m for m in (before, after) if m)
    seasons = {number(m[1] or m[2]) for m in labels}
    if len(seasons) > 1 or any(s < 1 or s > 999 for s in seasons):
        return None, '片单来源的季数冲突或无效'
    return next(iter(seasons), None), ''


def release_info(intro: str) -> tuple[str | None, int | None]:
    """Only dates immediately following a release cue are evidence."""
    text = unicodedata.normalize("NFKC", intro or "")
    dates: list[date] = []
    years: list[int] = []
    for cue in DATE_LABEL.finditer(text):
        # Do not let an unrelated year later in a long description become a date.
        snippet = text[cue.end():cue.end() + 48]
        exact = FULL_DATE.search(snippet)
        if exact and exact.start() <= 8:
            try:
                found = date(int(exact["year"]),
                             int(exact["month_cn"] or exact["month_num"]),
                             int(exact["day_cn"] or exact["day_num"]))
            except ValueError:
                continue
            dates.append(found)
            years.append(found.year)
            continue
        year = YEAR.search(snippet)
        if year and year.start() <= 8:
            years.append(int(year.group(1)))
    if dates:
        first = min(dates)
        return first.isoformat(), first.year
    return None, min(years) if years else None


def country_info(video_title: str, intro: str) -> str | None:
    """Use a release-line territory first, then an explicit title prefix."""
    text = unicodedata.normalize("NFKC", intro or "")
    for cue in DATE_LABEL.finditer(text):
        line = text[cue.end():].partition("\n")[0][:100]
        # A nearby release year is required; unrelated parenthesized text in
        # the description must not become the film's country.
        year = YEAR.search(line)
        if not year or year.start() > 8:
            continue
        for match in re.finditer(r"\(([^()]*)\)", line[year.end():]):
            label = match.group(1).strip()
            if label in {"全球", "全世界", "国际", "未定", "待定"}:
                continue
            for country in COUNTRIES:
                if label == country or label in (country + "电视台", country + "院线"):
                    return country
    prefix = unicodedata.normalize("NFKC", video_title or "").split("《", 1)[0]
    for country in COUNTRIES:
        if country in prefix:
            return country
    return None


class FilmWatchlistAdapter:
    def __init__(self, cfg):
        self.cfg = cfg
        self.section = cfg["film_watchlist"]

    def identity(self):
        return read_bili_sync_credential(self.section["bili_sync_db"])[0]

    def sync_metadata(self, store, source, account):
        from .film_store import ingest_bilibili
        key = "bili_identity:" + account
        previous = store.setting(key)
        if previous and previous != self.identity():
            raise SyncError("bili_account_changed")
        identity, folder, videos = self.scan()
        if previous and previous != identity:
            raise SyncError("bili_account_changed")
        stats = ingest_bilibili(store.db, account, videos)
        store.setting(key, identity)
        store.setting("film_watchlist_last_result", str(stats))
        store.update(source, account, scan_status="complete", scan_reason="end",
                     last_scan=time.time(), error=None)
        logging.getLogger("favsync").info(
            "%s: complete folder=%s videos=%d titles=%d without_title=%d",
            source, folder, stats["videos"], stats["titles"], stats["without_title"])

    def scan(self):
        uid, credential = read_bili_sync_credential(self.section["bili_sync_db"])
        session = requests.Session()
        session.trust_env = False
        session.headers.update({
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com/",
        })
        session.cookies.update({key: str(value) for key, value in (
            ("SESSDATA", credential["sessdata"]),
            ("bili_jct", credential.get("bili_jct")),
            ("buvid3", credential.get("buvid3")),
            ("DedeUserID", uid),
        ) if value})
        proxy = proxy_url(self.cfg, "bili")
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
        folder_id = self.section["folder_id"]
        items = []
        seen = set()
        returned_count = 0
        folder_name = None
        try:
            for page in range(1, 101):
                try:
                    response = session.get(
                        "https://api.bilibili.com/x/v3/fav/resource/list",
                        params={"media_id": folder_id, "pn": page, "ps": 20, "order": "mtime"},
                        timeout=20,
                    )
                except requests.RequestException as exc:
                    raise SyncError("network_error") from exc
                if response.status_code in (401, 403):
                    raise SyncError("auth_required")
                if response.status_code in (412, 429):
                    raise SyncError("rate_limited")
                if not response.ok:
                    raise SyncError("http_error")
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise SyncError("invalid_response") from exc
                code = payload.get("code")
                if code in (-101, -403):
                    raise SyncError("auth_required")
                if code in (-412, -429):
                    raise SyncError("rate_limited")
                if code != 0 or not isinstance(payload.get("data"), dict):
                    raise SyncError("invalid_response")
                data = payload["data"]
                info = data.get("info") or {}
                if str(info.get("mid")) != uid or str(info.get("id")) != str(folder_id):
                    raise SyncError("bili_folder_mismatch")
                folder_name = info.get("title") or ""
                medias = data.get("medias") or []
                if not isinstance(medias, list):
                    raise SyncError("invalid_response")
                returned_count += len(medias)
                for media in medias:
                    bvid = media.get("bvid") or media.get("bv_id")
                    if not isinstance(bvid, str) or not re.fullmatch(r"BV[A-Za-z0-9]{10}", bvid):
                        continue
                    if bvid in seen:
                        raise SyncError("scan_incomplete")
                    seen.add(bvid)
                    items.append({"bvid": bvid, "title": media.get("title") or "",
                                  "intro": media.get("intro") or ""})
                if not data.get("has_more"):
                    count = info.get("media_count")
                    if count is not None and returned_count != int(count):
                        raise SyncError("scan_incomplete")
                    return uid, folder_name, items
            raise SyncError("scan_incomplete")
        finally:
            session.close()
