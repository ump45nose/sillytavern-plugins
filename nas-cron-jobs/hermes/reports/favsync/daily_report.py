#!/usr/bin/env python3
"""Emit a Telegram-ready alert only when Favsync reports an anomaly."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Taipei")
CONTAINER = "favsync-favsync-1"
SOURCE_LABELS = {
    "telegram": "Telegram",
    "telegram_notice": "Telegram Bot 投递",
    "x_bookmarks": "X 书签",
    "x_likes": "X 点赞",
    "eh_favorites": "EH 收藏",
    "xhs_favorites": "小红书收藏",
    "xhs_likes": "小红书点赞",
    "xhs_creators": "小红书作者缓存",
    "pixiv_art_public": "Pixiv 公开图片",
    "pixiv_art_private": "Pixiv 私密图片",
    "pixiv_novel_public": "Pixiv 公开小说",
    "pixiv_novel_private": "Pixiv 私密小说",
    "wallabag_entries": "Wallabag",
    "film_watchlist": "B 站影视片单",
}
KIND_LABELS = {
    "content": "Favsync 内容同步",
    "cookiecloud": "CookieCloud 同步",
    "source:film_watchlist": "B 站影视片单",
}
NORMAL_STATES = {
    "complete", "disabled", "awaiting_start_date", "idle", "partial", "cached"
}
SUCCESS_RESULTS = {"success", "succeeded", "complete", "completed", "ok"}


def clean_detail(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").split())
    return text[:240] or fallback


def load_status() -> dict:
    command = [
        "/usr/bin/docker", "exec", CONTAINER,
        "favsync", "--config", "/app/config.toml", "status",
    ]
    result = subprocess.run(command, capture_output=True, text=True,
                            timeout=45, check=False)
    if result.returncode:
        raise RuntimeError("Favsync status command failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Favsync status output is invalid JSON") from exc


def collect_problems(status: dict, since: datetime) -> list[tuple[str, str]]:
    problems: list[tuple[str, str]] = []

    for record in status.get("execution_history", []):
        try:
            finished = datetime.fromtimestamp(
                float(record["finished_at"]), TIMEZONE
            )
        except (KeyError, TypeError, ValueError, OSError):
            continue
        result = str(record.get("result") or "failed").lower()
        if finished >= since and result not in SUCCESS_RESULTS:
            kind = str(record.get("kind") or "Favsync 执行")
            platform = KIND_LABELS.get(kind, kind)
            problems.append((platform, f"{finished:%m-%d %H:%M} 执行结果：{clean_detail(result, 'failed')}"))

    for source in status.get("sources", []):
        scan_status = str(source.get("scan_status") or "unknown")
        error = source.get("error")
        if scan_status not in NORMAL_STATES or error:
            name = str(source.get("name") or "unknown")
            platform = SOURCE_LABELS.get(name, name)
            detail = clean_detail(error or scan_status, "未知异常")
            problems.append((platform, detail))

    for bundle in status.get("bundle_errors", []):
        if bundle.get("bundle_status") == "skipped_invalid":
            continue
        platform = clean_detail(bundle.get("platform"), "未知平台")
        count = bundle.get("count", 0)
        detail = clean_detail(bundle.get("error"), "下载失败")
        problems.append((platform, f"正文/附件处理失败：{detail}（{count} 条）"))

    for asset in status.get("download_errors", []):
        # The user explicitly excluded unavailable X content from alerts.
        # Keep its durable download status and execution history unchanged.
        if asset.get("platform") == "x" and asset.get("error") == "content_unavailable":
            continue
        platform = clean_detail(asset.get("platform"), "未知平台")
        count = asset.get("count", 0)
        detail = clean_detail(asset.get("error"), "附件失败")
        problems.append((platform, f"附件下载失败：{detail}（{count} 个）"))

    if (status.get("storage") or {}).get("paused_low_disk"):
        problems.append(("Favsync 存储", "磁盘空间过低，下载已暂停"))

    for service, state in (status.get("external_services") or {}).items():
        if state != "ok":
            problems.append((str(service), f"外部服务状态：{clean_detail(state, '异常')}"))

    incomplete = sum(
        int(row.get("count", 0) or 0)
        for row in status.get("wallabag_exports", [])
        if row.get("attachment_status") == "incomplete"
    )
    if incomplete:
        problems.append(("Wallabag", f"图片附件不完整（{incomplete} 条）"))

    return problems


def main() -> int:
    now = datetime.now(TIMEZONE)
    try:
        status = load_status()
        problems = collect_problems(status, now - timedelta(hours=24))
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        problems = [("Favsync 状态采集", clean_detail(exc, "无法读取运行状态"))]

    if not problems:
        return 0

    print(f"Favsync 异常告警 {now:%Y-%m-%d %H:%M}（过去24小时执行记录及当前状态）")
    for platform, detail in problems:
        print(f"问题平台：{platform}；问题：{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
