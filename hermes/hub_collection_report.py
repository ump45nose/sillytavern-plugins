#!/usr/bin/env python3
"""Emit only Hub collection anomalies, using run metadata rather than content freshness."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Taipei")
CONTAINER = "personal-crm-crm-1"
SERVICE = "personal-data-hub-collectors.service"
LABELS = {
    "crm": "CRM / 微信归档", "google": "Google 日历 / Tasks", "email": "邮件",
    "git": "Git", "plaud": "Plaud 录音归档", "memos": "Memos", "mem0": "Mem0",
    "skysight-raw": "电脑活动原始片段", "skysight-summaries": "电脑活动摘要",
    "hermes-reports": "Hermes 执行报告", "token-monitor": "Token Monitor",
    "shellcrash": "ShellCrash 流量", "legacy-evidence": "旧证据归档",
    "legacy-review-output": "旧复盘产物归档",
}
LEGACY_REASONS = {
    "segment_invalid": "电脑活动片段校验失败，部分数据未能归档",
    "PermissionError": "读取来源数据的权限不足",
    "FileNotFoundError": "采集所需的文件或程序不存在",
    "TimeoutError": "采集请求超时", "TimeoutExpired": "采集进程运行超时",
    "ConnectionError": "来源服务网络连接失败或中断",
    "OperationalError": "数据库连接或操作失败",
}


def instant(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError("invalid_run_timestamp")
    return parsed


def failure_reason(value):
    try:
        detail = json.loads(value or "")
    except (ValueError, TypeError):
        detail = None
    if isinstance(detail, dict) and isinstance(detail.get("reason"), str):
        reason = " ".join(detail["reason"].split())
        if reason and not re.search(r"https?://|Bearer |access_token|refresh_token", reason, re.I):
            return reason[:160]
    return LEGACY_REASONS.get(value if isinstance(value, str) else None,
                              "采集器执行失败，具体原因未记录")


def load_snapshot():
    result = subprocess.run(
        ["/usr/bin/docker", "exec", "-i", CONTAINER, "python", "-"],
        input=Path(__file__).with_name("hub_collection_probe.py").read_text(),
        capture_output=True, text=True, timeout=60, check=False,
    )
    if result.returncode:
        raise RuntimeError("hub_status_read_failed")
    value = json.loads(result.stdout)
    if (not isinstance(value, dict) or not isinstance(value.get("sources"), dict)
            or not isinstance(value.get("latest_runs"), dict)
            or not isinstance(value.get("latest_finished_runs"), dict)):
        raise ValueError("invalid_hub_status")
    return value


def service_state():
    result = subprocess.run(
        ["/usr/bin/systemctl", "is-active", SERVICE],
        capture_output=True, text=True, timeout=10, check=False,
    )
    state = result.stdout.strip()
    if state in ("active", "inactive", "failed", "activating", "deactivating", "unknown"):
        return state
    raise RuntimeError("collector_service_state_unavailable")


def collect_problems(snapshot, now):
    problems = []
    for source, settings in sorted(snapshot["sources"].items()):
        if not settings.get("enabled", True) or settings.get("collection_mode") == "push":
            continue
        label = LABELS.get(source, source)
        latest = snapshot["latest_runs"].get(source)
        if not latest:
            problems.append((label, "已启用周期采集，但没有运行记录"))
            continue
        state = latest["status"]
        completed = snapshot["latest_finished_runs"].get(source) if state == "running" else latest
        reason = (failure_reason(completed.get("error"))
                  if completed and completed["status"] in ("failed", "partial") else None)
        if state not in ("ok", "running", "failed", "partial"):
            reason = "采集状态无法识别"
        allowance = max(3 * int(settings.get("interval_seconds", 3600)), 3600)
        age = (now - instant(latest["started_at"] if state == "running"
                             else latest.get("ended_at") or latest["started_at"])).total_seconds()
        if age > allowance:
            stalled = (f"本轮采集已运行 {int(age // 60)} 分钟，超过正常时限" if state == "running"
                       else f"已 {int(age // 60)} 分钟没有完成采集")
            reason = f"{reason}；{stalled}" if reason else stalled
        if reason:
            problems.append((label, reason))
    return problems


def main():
    try:
        snapshot = load_snapshot()
        problems = collect_problems(snapshot, instant(snapshot["checked_at"]))
    except (OSError, subprocess.TimeoutExpired, RuntimeError, ValueError, KeyError, TypeError):
        problems = [("Hub 采集状态", "无法读取或解析采集运行记录")]
    try:
        state = service_state()
        if state != "active":
            detail = {"inactive": "采集服务未运行", "failed": "采集服务启动或运行失败",
                      "activating": "采集服务仍在启动", "deactivating": "采集服务正在停止",
                      "unknown": "找不到采集服务"}[state]
            problems.append(("周期采集服务", detail))
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        problems.append(("周期采集服务", "无法读取服务状态"))
    if problems:
        print("**Hub 采集异常**")
        for label, detail in problems:
            print(f"- {label}：{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
