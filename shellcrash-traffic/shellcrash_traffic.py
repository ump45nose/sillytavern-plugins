#!/usr/bin/env python3
"""Lightweight per-destination accounting from the Mihomo connections API."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import ipaddress
import json
import os
import re
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path


DEFAULT_DB = "/var/lib/shellcrash-traffic/traffic.sqlite3"
DEFAULT_CONFIG = "/tmp/ShellCrash/config.yaml"
DEFAULT_CONTROLLER = "http://127.0.0.1:9999"
POLL_SECONDS = 1.0
FLUSH_SECONDS = 10.0
STOP = False


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
CREATE TABLE IF NOT EXISTS traffic_hourly (
  bucket TEXT NOT NULL,
  destination_ip TEXT NOT NULL,
  host TEXT NOT NULL,
  process TEXT NOT NULL,
  source_ip TEXT NOT NULL,
  category TEXT NOT NULL,
  pool TEXT NOT NULL,
  source_tag TEXT NOT NULL,
  exit_node TEXT NOT NULL,
  rule TEXT NOT NULL,
  upload_bytes INTEGER NOT NULL DEFAULT 0,
  download_bytes INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (
    bucket, destination_ip, host, process, source_ip, category,
    pool, source_tag, exit_node, rule
  )
);
CREATE INDEX IF NOT EXISTS traffic_hourly_ip_idx
  ON traffic_hourly(destination_ip, bucket);
CREATE INDEX IF NOT EXISTS traffic_hourly_host_idx
  ON traffic_hourly(host, bucket);
CREATE TABLE IF NOT EXISTS collector_gaps (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS collector_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def iso_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def hour_bucket() -> str:
    return dt.datetime.now().astimezone().strftime("%Y-%m-%dT%H:00")


def open_db(path: str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.executescript(SCHEMA)
    return conn


def read_controller_secret(config_path: str) -> str:
    try:
        text = Path(config_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    match = re.search(r"(?m)^secret:\s*(.*?)\s*$", text)
    if not match:
        return ""
    return match.group(1).strip().strip("\"'")


def fetch_connections(controller: str, config_path: str) -> list[dict]:
    headers = {"Accept": "application/json"}
    secret = read_controller_secret(config_path)
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    req = urllib.request.Request(
        f"{controller.rstrip('/')}/connections", headers=headers
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        payload = json.load(response)
    connections = payload.get("connections", [])
    if not isinstance(connections, list):
        raise ValueError("Mihomo connections response is not a list")
    return connections


def destination_ip(metadata: dict) -> str:
    candidate = str(metadata.get("destinationIP") or "").strip()
    if candidate:
        return candidate
    remote = str(metadata.get("remoteDestination") or "").strip()
    if not remote:
        return "unknown"
    host = remote
    if remote.startswith("[") and "]" in remote:
        host = remote[1 : remote.index("]")]
    elif remote.count(":") == 1:
        host = remote.rsplit(":", 1)[0]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return "unknown"


def route_dimensions(connection: dict) -> tuple[str, str, str, str]:
    chains = [str(item) for item in connection.get("chains") or []]
    exit_node = chains[0] if chains else "unknown"
    category = chains[-1] if chains else "unknown"
    joined = " ".join(chains)
    if "DIRECT" in chains:
        pool = "direct"
    elif any(token in joined for token in ("机房稳定", "DC-DMIT", "DMIT")):
        pool = "datacenter"
    elif any(
        token in joined
        for token in (
            "廉价", "AIR-", "Grok", "[宝]", "[赔]", "[G]",
            "机场 PKM", "机场 GH", "机场 PQ",
        )
    ):
        pool = "airport"
    else:
        pool = "unknown"
    match = re.search(
        r"(?:^|[^A-Z])(AIR-(?:PKM|GH|PQ)|DC-DMIT)(?:[^A-Z]|$)", joined
    )
    if match:
        source_tag = match.group(1)
    else:
        short_match = re.search(r"\[(宝|赔|G)\]", joined)
        source_tag = short_match.group(1) if short_match else "unknown"
    return category, pool, source_tag, exit_node


def row_key(connection: dict) -> tuple[str, ...]:
    metadata = connection.get("metadata") or {}
    category, pool, source_tag, exit_node = route_dimensions(connection)
    host = str(
        metadata.get("host") or metadata.get("sniffHost") or "unknown"
    ).lower()
    process = str(metadata.get("process") or "unknown")
    source_ip = str(metadata.get("sourceIP") or "unknown")
    rule_name = str(connection.get("rule") or "unknown")
    rule_payload = str(connection.get("rulePayload") or "")
    rule = f"{rule_name}:{rule_payload}" if rule_payload else rule_name
    return (
        hour_bucket(), destination_ip(metadata), host, process, source_ip,
        category, pool, source_tag, exit_node, rule,
    )


def flush(conn: sqlite3.Connection, pending: dict[tuple[str, ...], list[int]]) -> None:
    if not pending:
        return
    conn.executemany(
        """
        INSERT INTO traffic_hourly (
          bucket, destination_ip, host, process, source_ip, category,
          pool, source_tag, exit_node, rule, upload_bytes, download_bytes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (
          bucket, destination_ip, host, process, source_ip, category,
          pool, source_tag, exit_node, rule
        ) DO UPDATE SET
          upload_bytes = upload_bytes + excluded.upload_bytes,
          download_bytes = download_bytes + excluded.download_bytes
        """,
        [(*key, values[0], values[1]) for key, values in pending.items()],
    )
    conn.execute(
        "INSERT INTO collector_meta(key,value) VALUES('last_sample',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (iso_now(),),
    )
    conn.commit()
    pending.clear()


def signal_stop(_signum: int, _frame: object) -> None:
    global STOP
    STOP = True


def run_collector(args: argparse.Namespace) -> int:
    signal.signal(signal.SIGTERM, signal_stop)
    signal.signal(signal.SIGINT, signal_stop)
    conn = open_db(args.db)
    previous: dict[str, tuple[int, int]] = {}
    pending: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])
    last_flush = time.monotonic()
    initial_snapshot = True
    gap_id: int | None = None

    last_sample = conn.execute(
        "SELECT value FROM collector_meta WHERE key='last_sample'"
    ).fetchone()
    if last_sample:
        try:
            old = dt.datetime.fromisoformat(last_sample[0])
            if (dt.datetime.now().astimezone() - old).total_seconds() > 5:
                cursor = conn.execute(
                    "INSERT INTO collector_gaps(started_at,ended_at,reason) VALUES(?,?,?)",
                    (last_sample[0], iso_now(), "collector not running"),
                )
                gap_id = cursor.lastrowid
                conn.commit()
                gap_id = None
        except ValueError:
            pass

    while not STOP:
        started = time.monotonic()
        try:
            connections = fetch_connections(args.controller, args.config)
            if gap_id is not None:
                conn.execute(
                    "UPDATE collector_gaps SET ended_at=? WHERE id=?",
                    (iso_now(), gap_id),
                )
                conn.commit()
                gap_id = None
            current_ids: set[str] = set()
            for item in connections:
                connection_id = str(item.get("id") or "")
                if not connection_id:
                    continue
                current_ids.add(connection_id)
                upload = max(0, int(item.get("upload") or 0))
                download = max(0, int(item.get("download") or 0))
                old_upload, old_download = previous.get(connection_id, (0, 0))
                if initial_snapshot:
                    delta_upload = delta_download = 0
                else:
                    delta_upload = upload - old_upload if upload >= old_upload else upload
                    delta_download = download - old_download if download >= old_download else download
                previous[connection_id] = (upload, download)
                if delta_upload or delta_download:
                    values = pending[row_key(item)]
                    values[0] += delta_upload
                    values[1] += delta_download
            previous = {key: previous[key] for key in current_ids}
            initial_snapshot = False
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
            if gap_id is None:
                cursor = conn.execute(
                    "INSERT INTO collector_gaps(started_at,reason) VALUES(?,?)",
                    (iso_now(), type(error).__name__),
                )
                conn.commit()
                gap_id = cursor.lastrowid

        if time.monotonic() - last_flush >= FLUSH_SECONDS:
            flush(conn, pending)
            last_flush = time.monotonic()
        delay = max(0.05, args.interval - (time.monotonic() - started))
        time.sleep(delay)

    flush(conn, pending)
    if gap_id is not None:
        conn.execute(
            "UPDATE collector_gaps SET ended_at=? WHERE id=?", (iso_now(), gap_id)
        )
        conn.commit()
    conn.close()
    return 0


GROUPS = {
    "ip": "destination_ip",
    "host": "host",
    "process": "process",
    "category": "category",
    "pool": "pool",
    "source": "source_tag",
    "node": "exit_node",
}


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def sum_by(conn: sqlite3.Connection, column: str, month: str, ip: str | None,
           top: int) -> list[tuple[str, int, int, int]]:
    clauses = ["bucket LIKE ?"]
    params: list[object] = [f"{month}%"]
    if ip:
        clauses.append("destination_ip = ?")
        params.append(ip)
    rows = conn.execute(
        f"""
        SELECT {column}, SUM(upload_bytes), SUM(download_bytes),
               SUM(upload_bytes + download_bytes)
        FROM traffic_hourly WHERE {' AND '.join(clauses)}
        GROUP BY {column} ORDER BY 4 DESC LIMIT ?
        """,
        (*params, top),
    ).fetchall()
    return [(str(row[0]), int(row[1] or 0), int(row[2] or 0), int(row[3] or 0))
            for row in rows]


def daily_totals(conn: sqlite3.Connection, month: str,
                 ip: str | None) -> list[tuple[str, int]]:
    clauses = ["bucket LIKE ?"]
    params: list[object] = [f"{month}%"]
    if ip:
        clauses.append("destination_ip = ?")
        params.append(ip)
    rows = conn.execute(
        f"""
        SELECT substr(bucket, 1, 10) AS day, SUM(upload_bytes + download_bytes)
        FROM traffic_hourly WHERE {' AND '.join(clauses)}
        GROUP BY day ORDER BY day
        """,
        params,
    ).fetchall()
    return [(str(row[0]), int(row[1] or 0)) for row in rows]


def bar_chart(rows: list[tuple[str, int, int, int]], title: str) -> str:
    """Horizontal upload/download bars, pure SVG so the file stays standalone."""
    if not rows:
        return f"<section><h2>{escape(title)}</h2><p class='muted'>无数据</p></section>"
    width, row_height, gap, label_width = 900, 26, 8, 250
    height = len(rows) * (row_height + gap) + 10
    peak = max(total for _, _, _, total in rows) or 1
    track = width - label_width - 150
    parts = [
        f"<section><h2>{escape(title)}</h2>",
        f"<svg viewBox='0 0 {width} {height}' width='100%' "
        f"role='img' aria-label='{escape(title)}' class='chart'>",
    ]
    for index, (label, upload, download, total) in enumerate(rows):
        y = index * (row_height + gap) + 4
        up_w = max(1, int(track * upload / peak)) if upload else 0
        down_w = max(1, int(track * download / peak)) if download else 0
        text = escape(label[:38]) or "(unknown)"
        parts.append(
            f"<text x='0' y='{y + row_height * 0.68}' class='lab'>{text}</text>"
        )
        parts.append(
            f"<rect x='{label_width}' y='{y}' width='{up_w}' height='{row_height // 2 - 1}' "
            f"class='up'><title>上传 {escape(human_bytes(upload))}</title></rect>"
        )
        parts.append(
            f"<rect x='{label_width}' y='{y + row_height // 2 + 1}' width='{down_w}' "
            f"height='{row_height // 2 - 1}' class='down'>"
            f"<title>下载 {escape(human_bytes(download))}</title></rect>"
        )
        parts.append(
            f"<text x='{label_width + max(up_w, down_w) + 8}' y='{y + row_height * 0.68}' "
            f"class='val'>{escape(human_bytes(total))}</text>"
        )
    parts.append("</svg>")
    parts.append(
        "<p class='legend'><span class='sw up'></span>上传"
        "<span class='sw down'></span>下载</p></section>"
    )
    return "".join(parts)


def trend_chart(days: list[tuple[str, int]], title: str) -> str:
    if not days:
        return f"<section><h2>{escape(title)}</h2><p class='muted'>无数据</p></section>"
    width, height = 900, 220
    pad_left, pad_bottom, pad_top = 55, 26, 12
    peak = max(total for _, total in days) or 1
    step = (width - pad_left - 20) / max(1, len(days) - 1)
    plot_height = height - pad_bottom - pad_top
    points = [
        (
            pad_left + index * step,
            pad_top + plot_height - (total / peak) * plot_height,
            total,
        )
        for index, (_, total) in enumerate(days)
    ]
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
    area = (
        f"{pad_left},{pad_top + plot_height} "
        + polyline
        + f" {points[-1][0]:.1f},{pad_top + plot_height}"
    )
    grid = "".join(
        f"<line x1='{pad_left}' y1='{pad_top + plot_height * f:.2f}' "
        f"x2='{width - 20}' y2='{pad_top + plot_height * f:.2f}' class='grid'/>"
        f"<text x='0' y='{pad_top + plot_height * f + 4:.1f}' class='tick'>"
        f"{escape(human_bytes(peak * (1 - f)))}</text>"
        for f in (0, 0.25, 0.5, 0.75, 1.0)
    )
    stride = max(1, len(days) // 12)
    labels = "".join(
        f"<text x='{x:.1f}' y='{height - 8}' class='tick' "
        f"text-anchor='middle'>{escape(day[5:])}</text>"
        for index, ((x, _, _), (day, _)) in enumerate(zip(points, days))
        if index % stride == 0
    )
    dots = "".join(
        f"<circle cx='{x:.1f}' cy='{y:.1f}' r='3' class='dot'>"
        f"<title>{escape(day)} {escape(human_bytes(total))}</title></circle>"
        for (x, y, total), (day, _) in zip(points, days)
    )
    return (
        f"<section><h2>{escape(title)}</h2>"
        f"<svg viewBox='0 0 {width} {height}' width='100%' role='img' "
        f"class='chart' aria-label='{escape(title)}'>{grid}"
        f"<polygon points='{area}' class='area'/>"
        f"<polyline points='{polyline}' class='line'/>{dots}{labels}</svg></section>"
    )


HTML_STYLE = """
:root { color-scheme: light dark; --fg: #1f2328; --muted: #6b7280;
        --up: #3b82f6; --down: #10b981; --line: #8b5cf6; --card: #f6f8fa; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #e6edf3; --muted: #9aa4b2; --card: #161b22; }
  body { background: #0d1117; }
}
* { box-sizing: border-box; }
body { font: 14px/1.5 -apple-system, "Segoe UI", "Noto Sans SC", sans-serif;
       color: var(--fg); margin: 0 auto; max-width: 980px; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 15px; margin: 28px 0 8px; }
p.muted, .muted { color: var(--muted); }
.meta { color: var(--muted); font-size: 13px; }
.cards { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 8px; }
.card { background: var(--card); border: 1px solid rgba(128,128,128,.25);
        border-radius: 10px; padding: 10px 14px; min-width: 150px; }
.card b { display: block; font-size: 18px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 5px 8px; border-bottom: 1px solid rgba(128,128,128,.2); }
th { color: var(--muted); font-weight: 600; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; }
.chart { display: block; margin: 4px 0; }
.lab { font-size: 12px; fill: currentColor; }
.val { font-size: 12px; fill: var(--muted); }
.tick { font-size: 10px; fill: var(--muted); }
.grid { stroke: rgba(128,128,128,.25); stroke-width: 1; }
.line { fill: none; stroke: var(--line); stroke-width: 2; }
.area { fill: var(--line); opacity: .12; }
.dot { fill: var(--line); }
rect.up { fill: var(--up); }
rect.down { fill: var(--down); }
.legend { font-size: 12px; color: var(--muted); margin: 2px 0 0; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 2px;
      margin: 0 4px 0 12px; }
.sw.up { background: var(--up); } .sw.down { background: var(--down); }
code { background: var(--card); padding: 1px 5px; border-radius: 4px; }
"""


def write_html_report(path: str, month: str, ip: str | None, conn: sqlite3.Connection,
                      gaps: list[tuple[str, str, str]]) -> None:
    categories = sum_by(conn, "category", month, ip, 20)
    pools = sum_by(conn, "pool", month, ip, 10)
    sources = sum_by(conn, "source_tag", month, ip, 10)
    nodes = sum_by(conn, "exit_node", month, ip, 12)
    hosts = sum_by(conn, "host", month, ip, 20)
    host_category = dict(
        conn.execute(
            "SELECT host, category FROM traffic_hourly "
            "GROUP BY host, category ORDER BY SUM(upload_bytes+download_bytes) DESC"
        ).fetchall()
    )
    days = daily_totals(conn, month, ip)
    total = sum(total for _, _, _, total in categories)
    upload = sum(up for _, up, _, _ in categories)
    download = sum(down for _, _, down, _ in categories)

    cards = [
        ("总流量", human_bytes(total)),
        ("上传 / 下载", f"{human_bytes(upload)} / {human_bytes(download)}"),
        ("策略组", str(len(categories))),
        ("目标域名", str(len(hosts))),
        ("采集缺口", str(len(gaps))),
    ]
    card_html = "".join(
        f"<div class='card'><span class='muted'>{escape(label)}</span>"
        f"<b>{escape(value)}</b></div>"
        for label, value in cards
    )
    gap_html = ""
    if gaps:
        gap_html = (
            "<h2>采集缺口</h2><table><tr><th>开始</th><th>结束</th><th>原因</th></tr>"
            + "".join(
                f"<tr><td>{escape(start)}</td><td>{escape(end)}</td>"
                f"<td>{escape(reason)}</td></tr>"
                for start, end, reason in gaps[:10]
            )
            + "</table>"
        )
    host_rows = "".join(
        f"<tr><td>{escape(host)}</td><td>{escape(host_category.get(host, '-'))}</td>"
        f"<td class='n'>{escape(human_bytes(up))}</td>"
        f"<td class='n'>{escape(human_bytes(down))}</td>"
        f"<td class='n'>{escape(human_bytes(total))}</td></tr>"
        for host, up, down, total in hosts
    )
    node_rows = "".join(
        f"<tr><td>{escape(node[:70])}</td><td class='n'>{escape(human_bytes(total))}</td></tr>"
        for node, _, _, total in nodes
    )
    title = f"代理用量分析 · {month}" + (f" · {ip}" if ip else "")
    document = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{HTML_STYLE}</style></head><body>
<h1>{escape(title)}</h1>
<p class="meta">由 <code>shellcrash-traffic-report --html</code> 生成于
{escape(iso_now())}；数据来自 Mihomo <code>/connections</code> 采样，
不含请求路径、内容与凭据。</p>
<div class="cards">{card_html}</div>
{trend_chart(days, "每日流量趋势")}
{bar_chart(categories, "按策略组（分流组）")}
{bar_chart(pools, "按出口池")}
{bar_chart(sources, "按订阅来源")}
<h2>出口节点 Top {len(nodes)}</h2>
<table><tr><th>节点</th><th class="n">流量</th></tr>{node_rows}</table>
<h2>目标域名 Top {len(hosts)}</h2>
<table><tr><th>域名</th><th>策略组</th><th class="n">上传</th>
<th class="n">下载</th><th class="n">合计</th></tr>{host_rows}</table>
{gap_html}
</body></html>
"""
    target = Path(path)
    if target.parent and str(target.parent):
        target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".partial")
    staging.write_text(document, encoding="utf-8")
    staging.replace(target)


def run_report(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"\d{4}-\d{2}", args.month):
        raise SystemExit("--month must use YYYY-MM")
    column = GROUPS[args.group]
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    clauses = ["bucket LIKE ?"]
    params: list[object] = [f"{args.month}%"]
    if args.ip:
        clauses.append("destination_ip = ?")
        params.append(args.ip)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT {column}, SUM(upload_bytes), SUM(download_bytes),
               SUM(upload_bytes + download_bytes)
        FROM traffic_hourly WHERE {where}
        GROUP BY {column} ORDER BY 4 DESC LIMIT ?
        """,
        (*params, args.top),
    ).fetchall()
    coverage = conn.execute(
        "SELECT MIN(bucket), MAX(bucket), SUM(upload_bytes+download_bytes) "
        f"FROM traffic_hourly WHERE {where}", params
    ).fetchone()
    gaps = conn.execute(
        "SELECT started_at, COALESCE(ended_at,'OPEN'), reason FROM collector_gaps "
        "WHERE started_at LIKE ? ORDER BY started_at", (f"{args.month}%",)
    ).fetchall()

    output_rows = [
        {
            args.group: row[0], "upload_bytes": row[1],
            "download_bytes": row[2], "total_bytes": row[3],
        }
        for row in rows
    ]
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=output_rows[0].keys() if output_rows else [args.group, "upload_bytes", "download_bytes", "total_bytes"])
            writer.writeheader()
            writer.writerows(output_rows)

    print(f"Month: {args.month}  Group: {args.group}  Filter IP: {args.ip or '-'}")
    print(f"Coverage: {coverage[0] or '-'} .. {coverage[1] or '-'}  Accounted: {human_bytes(coverage[2] or 0)}")
    print(f"Gaps: {len(gaps)}" + (" (measurement is incomplete)" if gaps else ""))
    if gaps:
        for started_at, ended_at, reason in gaps[:5]:
            print(f"  gap {started_at} .. {ended_at}: {reason}")
    print()
    print(f"{'VALUE':48} {'UPLOAD':>12} {'DOWNLOAD':>12} {'TOTAL':>12}")
    for row in output_rows:
        value = str(row[args.group])[:48]
        print(f"{value:48} {human_bytes(row['upload_bytes']):>12} {human_bytes(row['download_bytes']):>12} {human_bytes(row['total_bytes']):>12}")
    if args.csv:
        print(f"\nCSV: {args.csv}")
    if getattr(args, "html", None):
        write_html_report(args.html, args.month, args.ip, conn, gaps)
        print(f"HTML: {args.html}")
    conn.close()
    return 0


def parser() -> argparse.ArgumentParser:
    executable = Path(sys.argv[0]).name
    report_mode = executable.endswith("traffic-report")
    result = argparse.ArgumentParser()
    result.add_argument("--db", default=os.getenv("TRAFFIC_DB", DEFAULT_DB))
    if report_mode:
        result.add_argument("--month", default=dt.datetime.now().astimezone().strftime("%Y-%m"))
        result.add_argument("--group", choices=sorted(GROUPS), default="ip")
        result.add_argument("--top", type=int, default=50)
        result.add_argument("--ip")
        result.add_argument("--csv")
        result.add_argument(
            "--html",
            help="额外生成一份自包含 HTML 可视化报告（图表为内联 SVG，无外部依赖）",
        )
    else:
        result.add_argument("--controller", default=DEFAULT_CONTROLLER)
        result.add_argument("--config", default=DEFAULT_CONFIG)
        result.add_argument("--interval", type=float, default=POLL_SECONDS)
    result.set_defaults(report_mode=report_mode)
    return result


def main() -> int:
    args = parser().parse_args()
    return run_report(args) if args.report_mode else run_collector(args)


if __name__ == "__main__":
    raise SystemExit(main())
