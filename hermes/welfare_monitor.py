"""Daily new-item monitor for welfare sites and selected Linux.do feeds.

Hermes no-agent cron executes this file once per day. The first successful
fetch of each source establishes a baseline; later runs print only newly seen
items. Empty stdout intentionally means no Telegram delivery.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.cookiejar
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx


CHINA_TZ = ZoneInfo("Asia/Shanghai")
PROFILE_ROOT = Path("/home/hermes/.hermes/profiles/lingjun")
DB_PATH = PROFILE_ROOT / "data/welfare-monitor/state.db"
LOCK_PATH = PROFILE_ROOT / "data/welfare-monitor/run.lock"
LINUXDO_COOKIE_PATH = (
    PROFILE_ROOT / "secrets/welfare-monitor/linux.do_cookies.txt"
)
LDOH_COOKIE_PATH = PROFILE_ROOT / "secrets/welfare-monitor/ldoh_cookies.txt"

USER_AGENT = "Mozilla/5.0 (compatible; welfare-monitor/1.0)"
MAX_MESSAGE_CHARS = 3800

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


@dataclass
class Item:
    source: str
    item_id: str
    canonical_id: str
    title: str
    url: str
    published_at: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    labels: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    fetcher: Callable[[], list[Item]]


def now_iso() -> str:
    return datetime.now(CHINA_TZ).isoformat(timespec="seconds")


def safe_text(value: Any, limit: int = 100) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("<", "＜").replace(">", "＞").replace("&", "＆")
    return textwrap.shorten(text, width=limit, placeholder="…")


def safe_url(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else fallback


def client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "timeout": 30,
        "follow_redirects": True,
        "headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    }
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        kwargs["proxy"] = proxy
    return kwargs


def load_cookie_jar(path: Path) -> http.cookiejar.MozillaCookieJar:
    if not path.is_file():
        raise FileNotFoundError(f"缺少会话文件：{path.name}")
    if path.stat().st_mode & 0o007:
        raise PermissionError(f"会话文件不得向其他本机用户开放：{path.name}")
    jar = http.cookiejar.MozillaCookieJar(str(path))
    jar.load(ignore_discard=True, ignore_expires=False)
    if not list(jar):
        raise ValueError(f"会话文件没有有效 Cookie：{path.name}")
    return jar


def get_response(
    url: str,
    *,
    cookies: http.cookiejar.CookieJar | None = None,
    accept: str = "application/json",
) -> httpx.Response:
    kwargs = client_kwargs()
    kwargs["headers"]["Accept"] = accept
    if cookies is not None:
        kwargs["cookies"] = cookies
    with httpx.Client(**kwargs) as client:
        response = client.get(url)
    response.raise_for_status()
    return response


def curl_get(url: str, *, cookie_path: Path, accept: str) -> bytes:
    load_cookie_jar(cookie_path)
    result = subprocess.run(
        [
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--connect-timeout",
            "10",
            "--max-time",
            "30",
            "--max-filesize",
            "5242880",
            "--user-agent",
            USER_AGENT,
            "--header",
            f"Accept: {accept}",
            "--cookie",
            str(cookie_path),
            url,
        ],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        detail = safe_text(result.stderr.decode("utf-8", "replace"), 180)
        raise RuntimeError(f"curl exit {result.returncode}: {detail}")
    return result.stdout


def pick_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (
                payload[key]
                for key in ("sites", "items", "data", "results")
                if isinstance(payload.get(key), list)
            ),
            None,
        )
        if rows is None:
            raise ValueError("接口 JSON 中没有站点列表")
    else:
        raise ValueError("接口返回不是列表或对象")
    return [row for row in rows if isinstance(row, dict)]


def normalize_timestamp(value: Any) -> str:
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return safe_text(value, 40)


def generic_site_item(
    source: str,
    label: str,
    row: dict[str, Any],
    base_url: str,
) -> Item:
    title = safe_text(row.get("name") or row.get("title"), 90)
    if not title:
        raise ValueError("站点条目缺少名称")
    raw_id = row.get("id") or row.get("slug") or row.get("uuid")
    url = safe_url(
        row.get("url")
        or row.get("website")
        or row.get("homepage")
        or row.get("siteUrl"),
        base_url,
    )
    if raw_id in (None, ""):
        raw_id = hashlib.sha256(f"{title}\0{url}".encode()).hexdigest()[:24]
    created = normalize_timestamp(
        row.get("createdAt")
        or row.get("created_at")
        or row.get("addedAt")
        or row.get("added_at")
    )
    metadata = {
        key: safe_text(row.get(key), 24)
        for key in ("category", "status", "healthStatus")
        if row.get(key) not in (None, "")
    }
    return Item(
        source=source,
        item_id=str(raw_id),
        canonical_id=f"{source}:{raw_id}",
        title=title,
        url=url,
        published_at=created,
        metadata=metadata,
        labels={label},
    )


def fetch_sstx() -> list[Item]:
    base = "https://welfare.sstxww1.asia/"
    payload = get_response(f"{base}api/sites").json()
    items: list[Item] = []
    for row in pick_list(payload):
        if str(row.get("status") or "").lower() != "approved":
            continue
        item = generic_site_item("sstx", "公益站合集", row, base)
        item.url = f"{base}api/sites/{item.item_id}/visit"
        items.append(item)
    return items


def fetch_ldoh() -> list[Item]:
    base = "https://ldoh.105117.xyz/"
    payload = get_response(
        f"{base}api/sites",
        cookies=load_cookie_jar(LDOH_COOKIE_PATH),
    ).json()
    return [
        generic_site_item("ldoh", "LD OPEN HUB", row, base)
        for row in pick_list(payload)
    ]


def topic_id(guid: str, link: str) -> str:
    for value in (guid, link):
        match = re.search(r"(?:linux\.do-topic-|/t/(?:[^/]+/)?)(\d+)", value)
        if match:
            return match.group(1)
    return hashlib.sha256(f"{guid}\0{link}".encode()).hexdigest()[:24]


def fetch_linuxdo_rss(
    source: str,
    label: str,
    url: str,
    *,
    pages: int = 1,
) -> list[Item]:
    items: list[Item] = []
    seen_topics: set[str] = set()
    for page in range(pages):
        page_url = url if page == 0 else f"{url}?page={page}"
        document = curl_get(
            page_url,
            cookie_path=LINUXDO_COOKIE_PATH,
            accept="application/rss+xml, application/xml;q=0.9, */*;q=0.8",
        )
        root = ET.fromstring(document)
        page_items = root.findall("./channel/item")
        if not page_items:
            break
        added = 0
        for node in page_items:
            guid = (node.findtext("guid") or "").strip()
            link = (node.findtext("link") or "").strip()
            topic = topic_id(guid, link)
            if topic in seen_topics:
                continue
            seen_topics.add(topic)
            added += 1
            items.append(
                Item(
                    source=source,
                    item_id=topic,
                    canonical_id=f"linuxdo:{topic}",
                    title=safe_text(node.findtext("title"), 90),
                    url=safe_url(link, f"https://linux.do/t/{topic}"),
                    published_at=safe_text(node.findtext("pubDate"), 50),
                    labels={label},
                )
            )
        if added == 0:
            break
    if not items:
        raise ValueError("RSS 中没有主题条目")
    return items


def sources() -> list[Source]:
    return [
        Source("sstx", "公益站合集", fetch_sstx),
        Source("ldoh", "LD OPEN HUB", fetch_ldoh),
        Source(
            "linuxdo_welfare",
            "福利羊毛",
            lambda: fetch_linuxdo_rss(
                "linuxdo_welfare",
                "福利羊毛",
                "https://linux.do/c/welfare/36.rss",
                pages=4,
            ),
        ),
        Source(
            "linuxdo_public_welfare",
            "公益推广",
            lambda: fetch_linuxdo_rss(
                "linuxdo_public_welfare",
                "公益推广",
                "https://linux.do/tag/1515-tag/1515.rss",
            ),
        ),
    ]


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS source_state (
            source TEXT PRIMARY KEY,
            initialized_at TEXT,
            last_success_at TEXT,
            last_error TEXT,
            error_notified INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS seen (
            source TEXT NOT NULL,
            item_id TEXT NOT NULL,
            canonical_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY(source, item_id)
        )
        """
    )
    connection.commit()
    return connection


def process_success(
    connection: sqlite3.Connection,
    source: Source,
    items: list[Item],
) -> tuple[list[Item], bool]:
    row = connection.execute(
        "SELECT initialized_at, last_error FROM source_state WHERE source = ?",
        (source.key,),
    ).fetchone()
    initialized = bool(row and row["initialized_at"])
    recovered = bool(row and row["last_error"])
    new_items: list[Item] = []
    stamp = now_iso()
    for item in items:
        exists = connection.execute(
            "SELECT 1 FROM seen WHERE source = ? AND item_id = ?",
            (source.key, item.item_id),
        ).fetchone()
        if initialized and not exists:
            new_items.append(item)
        connection.execute(
            """
            INSERT OR IGNORE INTO seen(
                source, item_id, canonical_id, title, url, published_at, first_seen_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.key,
                item.item_id,
                item.canonical_id,
                item.title,
                item.url,
                item.published_at,
                stamp,
            ),
        )
    connection.execute(
        """
        INSERT INTO source_state(
            source, initialized_at, last_success_at, last_error, error_notified
        ) VALUES(?, ?, ?, NULL, 0)
        ON CONFLICT(source) DO UPDATE SET
            initialized_at = COALESCE(source_state.initialized_at, excluded.initialized_at),
            last_success_at = excluded.last_success_at,
            last_error = NULL,
            error_notified = 0
        """,
        (source.key, stamp, stamp),
    )
    connection.commit()
    return new_items, recovered


def process_failure(
    connection: sqlite3.Connection,
    source: Source,
    error: Exception,
    *,
    suppress: bool,
) -> str | None:
    detail = safe_text(f"{type(error).__name__}: {error}", 220)
    row = connection.execute(
        "SELECT last_error, error_notified FROM source_state WHERE source = ?",
        (source.key,),
    ).fetchone()
    already_notified = bool(
        row and row["last_error"] == detail and row["error_notified"]
    )
    notified = 1 if suppress or already_notified else 0
    connection.execute(
        """
        INSERT INTO source_state(source, last_error, error_notified)
        VALUES(?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            last_error = excluded.last_error,
            error_notified = excluded.error_notified
        """,
        (source.key, detail, notified),
    )
    connection.commit()
    if suppress or already_notified:
        return None
    connection.execute(
        "UPDATE source_state SET error_notified = 1 WHERE source = ?",
        (source.key,),
    )
    connection.commit()
    return f"{source.label}：{detail}"


def merge_items(items: list[Item]) -> list[Item]:
    merged: dict[str, Item] = {}
    for item in items:
        current = merged.get(item.canonical_id)
        if current is None:
            merged[item.canonical_id] = item
            continue
        current.labels.update(item.labels)
        if item.published_at > current.published_at:
            current.published_at = item.published_at
    return sorted(
        merged.values(),
        key=lambda item: (item.published_at, item.canonical_id),
        reverse=True,
    )


def metadata_suffix(item: Item) -> str:
    values = [value for value in item.metadata.values() if value]
    return f"（{' / '.join(values)}）" if values else ""


def format_output(items: list[Item], errors: list[str]) -> str:
    sections: list[str] = []
    if items:
        lines = [f"【福利监测新增】共 {len(items)} 项", ""]
        shown = 0
        for item in items:
            labels = "/".join(sorted(item.labels))
            block = (
                f"[{labels}] {item.title}{metadata_suffix(item)}\n"
                f"{item.url}"
            )
            candidate = "\n\n".join(lines + [block])
            if len(candidate) > MAX_MESSAGE_CHARS - 120:
                break
            lines.append(block)
            shown += 1
        if shown < len(items):
            lines.extend(["", f"另有 {len(items) - shown} 项因消息长度未展开。"])
        sections.append("\n\n".join(lines))
    if errors:
        sections.append(
            "【福利采集源异常】\n\n"
            + "\n".join(f"- {detail}" for detail in errors)
        )
    return "\n\n---\n\n".join(sections)


def run(*, baseline: bool = False) -> int:
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("已有福利采集任务在运行，本次跳过")
            return 0

        connection = connect_db()
        found: list[Item] = []
        errors: list[str] = []
        counts: list[str] = []
        try:
            for source in sources():
                try:
                    items = source.fetcher()
                    new_items, recovered = process_success(
                        connection,
                        source,
                        items,
                    )
                    found.extend(new_items)
                    counts.append(
                        f"{source.key}={len(items)}"
                        + (",recovered" if recovered else "")
                    )
                except Exception as exc:
                    logging.warning("%s 采集失败：%s", source.key, exc)
                    detail = process_failure(
                        connection,
                        source,
                        exc,
                        suppress=baseline,
                    )
                    if detail:
                        errors.append(detail)
                    counts.append(f"{source.key}=error")
        finally:
            connection.close()

    merged = merge_items(found)
    logging.info("福利采集完成：%s，新增=%d", " ".join(counts), len(merged))
    if baseline:
        print(f"baseline ok: {' '.join(counts)}")
    else:
        output = format_output(merged, errors)
        if output:
            print(output)
    return 0


def self_test() -> int:
    fixture = b"""<?xml version="1.0"?>
    <rss><channel><item>
      <title> test welfare </title>
      <link>https://linux.do/t/topic/123</link>
      <guid>linux.do-topic-123</guid>
      <pubDate>Sun, 26 Jul 2026 00:00:00 +0000</pubDate>
    </item></channel></rss>"""
    root = ET.fromstring(fixture)
    node = root.find("./channel/item")
    if node is None or topic_id(
        node.findtext("guid") or "",
        node.findtext("link") or "",
    ) != "123":
        raise AssertionError("RSS topic id parser failed")
    if safe_url("javascript:alert(1)", "fallback") != "fallback":
        raise AssertionError("URL validation failed")
    print("self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("run", "baseline", "self-test"),
        default="run",
    )
    args = parser.parse_args()
    if args.mode == "self-test":
        return self_test()
    return run(baseline=args.mode == "baseline")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("福利采集入口执行失败")
        print(f"福利采集入口执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
