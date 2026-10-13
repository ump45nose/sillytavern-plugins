"""Deterministic cross-border ETF premium alert entrypoint.

Hermes no-agent cron calls this file at 14:40-14:44 and 14:46 on weekdays.
Each invocation performs at most one request per configured product. The
14:46 invocation verifies that the collection window produced a complete
snapshot and reports missing or partial data.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
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


class NoCurrentMarketQuoteError(RuntimeError):
    """The quote or estimated NAV is not from today's market session."""


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


def state_values(prefix: str) -> list[str]:
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT value FROM state WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        ).fetchall()
    return [row[0] for row in rows]


def insert_price(item: dict[str, Any]) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO prices(source, item, price, quote_time, fetched_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                "etf_premium",
                item["code"],
                float(item["premium_pct"]),
                item.get("estimate_time") or item.get("quote_time"),
                china_now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )


def client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "timeout": 20,
        "follow_redirects": True,
    }
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        # httpx >=0.26 uses "proxy"; older versions use "proxies".
        try:
            with httpx.Client(proxy=proxy) as _:
                pass
            kwargs["proxy"] = proxy
        except TypeError:
            kwargs["proxies"] = proxy
    return kwargs


def http_get(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    with httpx.Client(**client_kwargs()) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


def http_get_json(url: str) -> dict[str, Any]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://quote.eastmoney.com/",
    }
    with httpx.Client(**client_kwargs()) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, dict):
        raise ValueError("行情接口返回不是 JSON 对象")
    return data


def tencent_market_prefix(exchange: str) -> str:
    """Map eastmoney exchange code to tencent market prefix."""
    return "sh" if exchange == "1" else "sz"


def tencent_quote_url(market_code: str) -> str:
    return f"https://qt.gtimg.cn/q={market_code}"


def parse_tencent_quote(raw_text: str, market_code: str) -> list[str]:
    """Extract the ~-delimited field array for one product from tencent response."""
    pattern = rf'v_{re.escape(market_code)}="(.+)"'
    match = re.search(pattern, raw_text.strip())
    if not match:
        raise ValueError(f"腾讯行情接口未返回 {market_code} 数据")
    return match.group(1).split("~")


def parse_tencent_time(raw: str) -> datetime:
    """Parse tencent timestamp like '20260727161500' into a CST datetime."""
    return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=CHINA_TZ)


def fetch_product(product: dict[str, Any]) -> dict[str, Any]:
    code = str(product["code"])
    exchange = str(product["exchange"])
    today = china_now().strftime("%Y-%m-%d")
    market_code = tencent_market_prefix(exchange) + code

    raw_text = http_get(tencent_quote_url(market_code))
    fields = parse_tencent_quote(raw_text, market_code)

    if len(fields) < 82:
        raise ValueError(f"{code} 腾讯行情字段不足（{len(fields)} < 82）")

    name = fields[1]
    price = float(fields[3])
    raw_time = fields[30]
    if not raw_time or len(raw_time) < 14:
        raise NoCurrentMarketQuoteError(f"{code} 未提供有效行情时间")

    quote_at = parse_tencent_time(raw_time).replace(tzinfo=None)
    if quote_at.strftime("%Y-%m-%d") != today:
        raise NoCurrentMarketQuoteError(f"{code} 最新行情不是今日：{raw_time}")

    # field[37] = 成交额（万元），field[38] has decimal percent but 37 is raw 万元
    amount_wan = float(fields[37] or 0)
    amount = amount_wan * 10_000

    # field[81] = 估算净值（IOPV / 基金参考净值）
    raw_est_nav = fields[81]
    if not raw_est_nav or float(raw_est_nav) <= 0:
        raise ValueError(f"{code} 估算净值无效：{raw_est_nav}")
    estimated_nav = float(raw_est_nav)

    if price <= 0 or estimated_nav <= 0:
        raise ValueError(f"{code} 的价格或估算净值无效")

    return {
        "code": code,
        "name": str(name or product.get("name") or code),
        "price": price,
        "estimated_nav": estimated_nav,
        "premium_pct": (price / estimated_nav - 1) * 100,
        "amount_yuan": amount,
        "quote_time": quote_at.strftime("%Y-%m-%d %H:%M:%S"),
        "estimate_time": None,  # tencent does not provide separate estimate time
    }


def format_amount(amount_yuan: float) -> str:
    if amount_yuan >= 100_000_000:
        return f"{amount_yuan / 100_000_000:.2f} 亿元"
    if amount_yuan >= 10_000:
        return f"{amount_yuan / 10_000:.0f} 万元"
    return f"{amount_yuan:.0f} 元"


def premium_tier(premium_pct: float, task_cfg: dict[str, Any]) -> str:
    tiers = task_cfg.get("tiers", [])
    if not isinstance(tiers, list):
        return ""
    valid = [
        tier
        for tier in tiers
        if isinstance(tier, dict) and "max_premium_pct" in tier
    ]
    for tier in sorted(valid, key=lambda row: float(row["max_premium_pct"])):
        if premium_pct <= float(tier["max_premium_pct"]):
            return str(tier.get("label", ""))
    return ""


def format_alert(
    matches: list[dict[str, Any]],
    task_cfg: dict[str, Any],
    *,
    complete: bool,
    received: int,
    expected: int,
) -> str:
    lines = ["**ETF 低溢价**"]
    if not complete:
        lines.append(f"- 行情不完整：{received}/{expected}")
    for item in matches:
        tier = premium_tier(float(item["premium_pct"]), task_cfg)
        suffix = f"（{tier}）" if tier else ""
        lines.append(f"- {item['code']} {item['name']}：估算溢价 {item['premium_pct']:+.2f}%{suffix}；"
                     f"成交 {format_amount(float(item['amount_yuan']))}；"
                     f"行情 {item.get('quote_time') or '-'} / 估值 {item.get('estimate_time') or '-'}")
    lines.append("估算值，交易前请复核。")
    return "\n".join(lines)


def compact_errors(errors: list[str], limit: int = 6) -> list[str]:
    return [error[:240] for error in errors[:limit]]


def collect_once(config: dict[str, Any], now: datetime) -> int:
    task_cfg = config.get("tasks", {}).get("etf_premium", {})
    if not task_cfg.get("enabled", False):
        return 0

    date_key = now.strftime("%Y-%m-%d")
    if state_get(f"etf_snapshot_valid:{date_key}") == "1":
        logging.info("今日已有完整 ETF 快照，跳过重复采集")
        return 0

    products = task_cfg.get("products", [])
    enabled_products = [
        product
        for product in products
        if isinstance(product, dict) and product.get("enabled", True)
    ]
    if not enabled_products:
        raise ValueError("tasks.etf_premium.products 未配置")

    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for product in enabled_products:
        code = str(product.get("code", "unknown"))
        try:
            item = fetch_product(product)
            results.append(item)
            insert_price(item)
        except Exception as exc:
            errors.append(f"{code}: {exc}")

    expected = len(enabled_products)
    complete = len(results) == expected
    snapshot = {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "received": len(results),
        "expected": expected,
        "complete": complete,
        "results": results,
        "errors": [error[:240] for error in errors[:6]],
    }
    state_set(
        f"etf_attempt:{date_key}:{now.strftime('%H%M')}",
        json.dumps(snapshot, ensure_ascii=False),
    )
    state_set(
        f"etf_snapshot_latest:{date_key}",
        json.dumps(snapshot, ensure_ascii=False),
    )

    if complete:
        state_set(f"etf_snapshot_valid:{date_key}", "1")
        state_set(f"etf_last_status:{date_key}", "valid")
    elif results:
        state_set(f"etf_last_status:{date_key}", "partial")
    else:
        state_set(f"etf_last_status:{date_key}", "source_error")

    if not results:
        logging.warning("ETF 本轮没有有效数据：%s", "; ".join(errors))
        return 0

    min_amount = float(task_cfg.get("min_amount_yuan", 0))
    threshold = float(task_cfg.get("alert_threshold_pct", 0.5))
    matches = [
        item
        for item in results
        if float(item["amount_yuan"]) >= min_amount
        and float(item["premium_pct"]) <= threshold
    ]
    logging.info("ETF 本轮完成：%d/%d，命中 %d", len(results), expected, len(matches))

    if matches and state_get(f"etf_alert_emitted:{date_key}") != "1":
        print(
            format_alert(
                matches,
                task_cfg,
                complete=complete,
                received=len(results),
                expected=expected,
            )
        )
        state_set(f"etf_alert_emitted:{date_key}", "1")
    return 0


def watchdog(config: dict[str, Any], now: datetime) -> int:
    task_cfg = config.get("tasks", {}).get("etf_premium", {})
    if not task_cfg.get("enabled", False):
        return 0

    date_key = now.strftime("%Y-%m-%d")
    emitted_key = f"etf_watchdog_emitted:{date_key}"
    if state_get(emitted_key) == "1":
        return 0
    if state_get(f"etf_snapshot_valid:{date_key}") == "1":
        logging.info("ETF 完整性检查通过")
        return 0

    latest_raw = state_get(f"etf_snapshot_latest:{date_key}")
    latest: dict[str, Any] = {}
    if latest_raw:
        try:
            parsed = json.loads(latest_raw)
            if isinstance(parsed, dict):
                latest = parsed
        except json.JSONDecodeError:
            pass

    received = int(latest.get("received") or 0)
    expected = int(
        latest.get("expected")
        or len(
            [
                product
                for product in task_cfg.get("products", [])
                if isinstance(product, dict) and product.get("enabled", True)
            ]
        )
    )
    errors = latest.get("errors") if isinstance(latest.get("errors"), list) else []

    if received:
        summary = f"有效行情仅 {received}/{expected}，无法完整判断溢价"
    else:
        summary = "未取得有效行情，无法判断溢价"

    lines = ["**ETF 采集异常**", "- " + summary]
    if errors:
        lines.extend(f"- {error}" for error in dict.fromkeys(compact_errors(errors, 4)))
    print("\n".join(lines))
    state_set(emitted_key, "1")
    return 0


def self_test(config: dict[str, Any]) -> int:
    init_db()
    task_cfg = config.get("tasks", {}).get("etf_premium", {})
    products = task_cfg.get("products", [])
    enabled = [
        item
        for item in products
        if isinstance(item, dict) and item.get("enabled", True)
    ]
    if not enabled:
        raise ValueError("没有启用的 ETF 产品")
    print(
        "self-test ok: "
        f"config={config_path()} db={db_path()} enabled_products={len(enabled)}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("auto", "collect", "watchdog", "self-test"),
        default="auto",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    init_db()
    now = china_now()

    if args.mode == "self-test":
        return self_test(config)
    if args.mode == "collect":
        return collect_once(config, now)
    if args.mode == "watchdog":
        return watchdog(config, now)

    if now.weekday() < 5 and now.hour == 14 and 40 <= now.minute <= 44:
        return collect_once(config, now)
    return watchdog(config, now)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("ETF 入口执行失败")
        print(f"ETF 入口执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
