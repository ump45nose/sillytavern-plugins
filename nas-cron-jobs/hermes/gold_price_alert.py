"""Deterministic gold-price alert entrypoint for Hermes no-agent cron.

This scenario is currently disabled in config.yaml, so no Hermes schedule is
created for it. When enabled later, each invocation performs one collection
pass and prints only messages that should be delivered.
"""

from __future__ import annotations

import argparse
import html
import logging
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import yaml


CHINA_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_CONFIG_PATH = Path(
    "/home/hermes/.hermes/profiles/lingjun/data/gold-alert/config.yaml"
)
DEFAULT_DB_PATH = Path(
    "/home/hermes/.hermes/profiles/lingjun/data/gold-alert/state.db"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tokens: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        value = normalize_text(html.unescape(data))
        if value:
            self.tokens.append(value)


def china_now() -> datetime:
    return datetime.now(CHINA_TZ).replace(tzinfo=None)


def config_path() -> Path:
    return Path(os.getenv("GOLD_ALERT_CONFIG", str(DEFAULT_CONFIG_PATH)))


def db_path() -> Path:
    return Path(os.getenv("GOLD_ALERT_DB", str(DEFAULT_DB_PATH)))


def load_config() -> dict[str, Any]:
    with config_path().open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("config.yaml 顶层必须是对象")
    return data


def connect_db() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                item TEXT NOT NULL,
                price REAL NOT NULL,
                quote_time TEXT,
                fetched_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                key TEXT PRIMARY KEY,
                last_alert_at TEXT NOT NULL
            )
            """
        )


def state_get(key: str) -> str | None:
    with connect_db() as conn:
        row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def state_set(key: str, value: str) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO state(key, value) VALUES(?, ?)",
            (key, value),
        )


def last_alert_at(key: str) -> datetime | None:
    with connect_db() as conn:
        row = conn.execute(
            "SELECT last_alert_at FROM alerts WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return None
    try:
        return datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def mark_alert(key: str) -> None:
    with connect_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO alerts(key, last_alert_at) VALUES(?, ?)",
            (key, china_now().strftime("%Y-%m-%d %H:%M:%S")),
        )


def can_alert(key: str, hours: int) -> bool:
    previous = last_alert_at(key)
    return previous is None or china_now() - previous >= timedelta(hours=hours)


def insert_price(
    source: str,
    item: str,
    price: float,
    quote_time: str | None,
) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO prices(source, item, price, quote_time, fetched_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                source,
                item,
                price,
                quote_time,
                china_now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_price(value: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", value.replace(",", ""))
    return float(match.group(1)) if match else None


def text_tokens(document: str) -> list[str]:
    parser = TextExtractor()
    parser.feed(document)
    parser.close()
    return parser.tokens


def slice_tokens(
    tokens: list[str],
    start_markers: list[str],
    end_markers: list[str],
) -> list[str]:
    start = 0
    for marker in start_markers:
        if marker in tokens:
            start = tokens.index(marker)
            break
    end = len(tokens)
    for marker in end_markers:
        if marker in tokens[start + 1 :]:
            end = min(end, tokens.index(marker, start + 1))
    return tokens[start:end]


def find_quote_time(tokens: list[str], start: int, window: int = 10) -> str | None:
    for value in tokens[start : start + window]:
        match = re.search(r"\d{4}-\d{2}-\d{2}", value)
        if match:
            return match.group(0)
        if "分钟前" in value or "小时前" in value:
            return value
    return None


def http_get(url: str) -> str:
    kwargs: dict[str, Any] = {"timeout": 20, "follow_redirects": True}
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        kwargs["proxy"] = proxy
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    with httpx.Client(**kwargs) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def fetch_named_prices(
    *,
    url: str,
    wanted: set[str],
    start_markers: list[str],
    end_markers: list[str],
    minimum: float,
    maximum: float,
) -> dict[str, dict[str, Any]]:
    tokens = text_tokens(http_get(url))
    section = slice_tokens(tokens, start_markers, end_markers)
    result: dict[str, dict[str, Any]] = {}
    for index, token in enumerate(section):
        if wanted and token not in wanted:
            continue
        if index + 1 >= len(section):
            continue
        price = extract_price(section[index + 1])
        if price is None or not minimum <= price <= maximum:
            continue
        result[token] = {
            "price": price,
            "quote_time": find_quote_time(section, index + 1),
        }
    return result


def format_price(
    name: str,
    price: float,
    threshold: float | None,
    quote_time: str | None,
) -> str:
    if threshold is None:
        return f"{name}：{price:g} 元/g，报价时间：{quote_time or '-'}"
    return (
        f"{name}：{price:g} 元/g，阈值：{threshold:g}，"
        f"差值：{price - threshold:+g}，报价时间：{quote_time or '-'}"
    )


def item_messages(
    kind: str,
    item: str,
    price: float,
    quote_time: str | None,
    threshold: float | None,
    config: dict[str, Any],
) -> list[str]:
    messages: list[str] = []
    repeat_hours = int(config.get("alert", {}).get("repeat_hours", 12))

    if threshold is not None and price <= threshold:
        key = f"threshold:{kind}:{item}:{threshold}"
        if can_alert(key, repeat_hours):
            messages.append(
                "【黄金价格阈值提醒】\n\n"
                f"{format_price(item, price, threshold, quote_time)}\n\n"
                "判断：已低于设置阈值；到店仍需核实工费、优惠和实际挂牌价。"
            )
            mark_alert(key)

    alert_cfg = config.get("alert", {})
    state_key = f"last_price:{kind}:{item}"
    previous_raw = state_get(state_key)
    state_set(state_key, str(price))
    if not alert_cfg.get("change_notify_enabled", True) or previous_raw is None:
        return messages

    try:
        previous = float(previous_raw)
    except ValueError:
        return messages
    difference = price - previous
    minimum_change = float(alert_cfg.get("change_abs_yuan", 10))
    change_key = f"change:{kind}:{item}"
    if abs(difference) >= minimum_change and can_alert(change_key, 6):
        direction = "上涨" if difference > 0 else "下跌"
        messages.append(
            "【黄金价格变化】\n\n"
            f"{item}：{price:g} 元/g\n"
            f"上次：{previous:g} 元/g\n"
            f"变化：{direction} {abs(difference):g} 元/g\n"
            f"报价时间：{quote_time or '-'}"
        )
        mark_alert(change_key)
    return messages


def daily_summary(
    brand_prices: dict[str, dict[str, Any]],
    base_prices: dict[str, dict[str, Any]],
    config: dict[str, Any],
) -> str | None:
    alert_cfg = config.get("alert", {})
    if not alert_cfg.get("daily_summary_enabled", True):
        return None
    now = china_now()
    if now.hour != int(alert_cfg.get("daily_summary_hour", 9)):
        return None
    key = f"daily_summary_sent:{now.strftime('%Y-%m-%d')}"
    if state_get(key) == "1":
        return None

    brand_thresholds = config.get("thresholds", {}).get("brand", {})
    base_thresholds = config.get("thresholds", {}).get("base", {})
    lines = ["【黄金价格日报】", ""]
    if base_prices:
        lines.append("基础金价：")
        for name, data in base_prices.items():
            lines.append(
                "- "
                + format_price(
                    name,
                    float(data["price"]),
                    float(base_thresholds[name]) if name in base_thresholds else None,
                    data.get("quote_time"),
                )
            )
    if brand_prices:
        lines.extend(["", "品牌挂牌价："])
        for name, data in brand_prices.items():
            lines.append(
                "- "
                + format_price(
                    name,
                    float(data["price"]),
                    float(brand_thresholds[name]) if name in brand_thresholds else None,
                    data.get("quote_time"),
                )
            )
    lines.extend(["", "备注：品牌挂牌价不是门店实付价。"])
    state_set(key, "1")
    return "\n".join(lines)


def run_once(config: dict[str, Any]) -> int:
    task_cfg = config.get("tasks", {}).get("gold", {})
    if not task_cfg.get("enabled", False):
        return 0

    sources = config.get("sources", {})
    brand_thresholds = config.get("thresholds", {}).get("brand", {})
    base_thresholds = config.get("thresholds", {}).get("base", {})
    errors: list[str] = []

    try:
        brand_prices = fetch_named_prices(
            url=str(sources["brand_url"]),
            wanted=set(config.get("brands", [])),
            start_markers=["金店今日金价", "品牌金店今日金价"],
            end_markers=["其他城市黄金首饰价格", "关于金价网", "品牌金店网点"],
            minimum=900,
            maximum=3000,
        )
    except Exception as exc:
        brand_prices = {}
        errors.append(f"品牌挂牌价：{exc}")

    try:
        base_prices = fetch_named_prices(
            url=str(sources["base_url"]),
            wanted=set(base_thresholds),
            start_markers=["今日金价查询表"],
            end_markers=["国际金价实时行情", "品牌金店今日金价", "关于金价网"],
            minimum=500,
            maximum=3000,
        )
    except Exception as exc:
        base_prices = {}
        errors.append(f"基础金价：{exc}")

    if not brand_prices and not base_prices:
        detail = "；".join(errors) if errors else "页面中没有解析到目标价格"
        print(f"黄金价格入口未取得有效数据：{detail}", file=sys.stderr)
        return 1

    messages: list[str] = []
    for kind, prices, thresholds in (
        ("brand", brand_prices, brand_thresholds),
        ("base", base_prices, base_thresholds),
    ):
        for name, data in prices.items():
            price = float(data["price"])
            quote_time = data.get("quote_time")
            insert_price(kind, name, price, quote_time)
            threshold = float(thresholds[name]) if name in thresholds else None
            messages.extend(
                item_messages(
                    kind,
                    name,
                    price,
                    quote_time,
                    threshold,
                    config,
                )
            )

    summary = daily_summary(brand_prices, base_prices, config)
    if summary:
        messages.append(summary)
    if errors:
        messages.append("【gold-alert 部分数据源异常】\n\n" + "\n".join(errors))
    if messages:
        print("\n\n---\n\n".join(messages))
    return 0


def self_test(config: dict[str, Any]) -> int:
    init_db()
    if "sources" not in config or "tasks" not in config:
        raise ValueError("配置缺少 sources 或 tasks")
    print(f"self-test ok: config={config_path()} db={db_path()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("run", "self-test"),
        default="run",
    )
    args = parser.parse_args()
    config = load_config()
    init_db()
    if args.mode == "self-test":
        return self_test(config)
    return run_once(config)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("黄金价格入口执行失败")
        print(f"黄金价格入口执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
