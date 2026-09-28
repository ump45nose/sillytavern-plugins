#!/usr/bin/env python3
"""Print a compact, secret-free Favsync report for Telegram delivery."""

from __future__ import annotations

import json
import subprocess
import sys
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
    "pixiv_art_public": "Pixiv 公开图片",
    "pixiv_art_private": "Pixiv 私密图片",
    "pixiv_novel_public": "Pixiv 公开小说",
    "pixiv_novel_private": "Pixiv 私密小说",
    "wallabag_entries": "Wallabag",
}
KIND_LABELS = {"content": "内容同步", "cookiecloud": "Cookie 同步"}
NORMAL_STATES = {"complete", "disabled", "awaiting_start_date", "idle"}


def load_status() -> dict:
    command = [
        "/usr/bin/docker", "exec", CONTAINER,
        "favsync", "--config", "/app/config.toml", "status",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        raise RuntimeError("status_command_failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("status_output_invalid") from exc


def main() -> int:
    now = datetime.now(TIMEZONE)
    try:
        status = load_status()
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        print(f"Favsync 每日运行结果 {now:%Y-%m-%d}")
        print("状态读取：失败")
        return 1

    since = now - timedelta(hours=24)
    executions = []
    for record in status.get("execution_history", []):
        try:
            finished = datetime.fromtimestamp(float(record["finished_at"]), TIMEZONE)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        if finished >= since:
            executions.append((finished, str(record.get("kind", "unknown")), str(record.get("result", "failed"))))

    lines = [f"Favsync 每日运行结果 {now:%Y-%m-%d}（过去24小时）"]
    if not executions:
        lines.append("无执行记录")
    else:
        for finished, kind, result in sorted(executions):
            label = KIND_LABELS.get(kind, kind)
            outcome = "成功" if result == "success" else "失败"
            lines.append(f"{finished:%m-%d %H:%M} {label}：{outcome}")

    problems = []
    for source in status.get("sources", []):
        scan_status = str(source.get("scan_status") or "unknown")
        error = source.get("error")
        if scan_status not in NORMAL_STATES or error:
            label = SOURCE_LABELS.get(str(source.get("name")), str(source.get("name")))
            detail = str(error or scan_status)
            problems.append(f"{label}={detail}")
    skipped = []
    for bundle in status.get("bundle_errors", []):
        platform = str(bundle.get("platform") or "unknown")
        error = str(bundle.get("error") or "unknown")
        count = bundle.get("count", 0)
        if bundle.get("bundle_status") == "skipped_invalid":
            skipped.append(f"{platform} 正文不足（{count} 条）")
            continue
        problems.append(f"{platform} 下载失败={error}（{count} 条）")
    for asset in status.get("download_errors", []):
        platform = str(asset.get("platform") or "unknown")
        error = str(asset.get("error") or "unknown")
        count = asset.get("count", 0)
        problems.append(f"{platform} 附件失败={error}（{count} 个）")
    storage = status.get("storage") or {}
    if storage.get("paused_low_disk"):
        problems.append("存储=paused_low_disk")
    for service, service_status in (status.get("external_services") or {}).items():
        if service_status != "ok":
            problems.append(f"{service}={service_status}")
    lines.append("当前异常：" + ("；".join(problems) if problems else "无"))
    if skipped:
        lines.append("已跳过：" + "；".join(skipped))
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
