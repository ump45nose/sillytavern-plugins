#!/usr/bin/env python3
"""Print an exception-only report from benefits cron delivery JSON files."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Taipei")
DELIVERY_ROOT = Path("/home/hermes/.hermes/profiles/lingjun/benefits-runtime/delivery")
TASKS = {
    "smzdm": "什么值得买",
    "v2ex": "V2EX",
    "aliyun": "阿里云开发者社区",
    "laowang": "laowang",
    "epic": "Epic 免费游戏",
    "rewards": "Microsoft Rewards",
}
REASONS = {
    "authentication_invalid": "登录失效",
    "human_required": "需要人工验证",
    "launcher_failed": "启动失败",
    "deadline_exceeded": "执行超时",
    "configuration_or_io_error": "配置或结果保存失败",
    "lock_busy": "已有任务执行中",
    "native_configuration_or_browser_error": "配置或浏览器异常",
    "full_intervention_pending": "遇到验证或登录问题",
}
TASK_LABELS = {
    "checkin": "签到",
    "reward": "奖励",
    "extra_reward": "额外奖励",
    "daily": "每日任务",
    "extra": "额外任务",
    "punchcards": "打卡任务",
    "desktop_search": "电脑搜索",
    "more_promotions": "更多活动",
    "claim": "领取任务",
    "app_daily": "APP签到",
    "app_promotions": "APP活动",
}
STATE_LABELS = {
    "unknown": "未确认",
    "blocked": "受阻",
    "failed": "失败",
    "busy": "执行中",
    "pending": "待处理",
}
EXECUTION_LABELS = {
    "failed": "执行失败",
    "busy": "仍在执行",
    "ok": "成功",
}
MAX_JSON_BYTES = 65536


def load_result(platform: str) -> tuple[dict | None, str | None]:
    path = DELIVERY_ROOT / f"{platform}.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            return None, "当日结果 JSON 超过读取限制"
        value = json.loads(raw)
    except FileNotFoundError:
        return None, "缺少当日结果 JSON"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "无法读取或解析结果 JSON"
    if not isinstance(value, dict):
        return None, "结果 JSON 格式无效"
    return value, None


def issue_for(platform: str, row: Mapping[str, object], day: str) -> str | None:
    if row.get("platform") != platform:
        return "结果平台标识与文件名不一致"
    if row.get("business_date") != day:
        found = row.get("business_date") or "未知"
        return f"缺少当日结果（最新结果日期：{found}）"

    parts: list[str] = []
    execution = row.get("execution_status")
    if execution != "ok":
        reason = str(row.get("reason") or "unknown")
        if execution == "busy":
            parts.append("任务仍在执行")
        else:
            state = str(execution or "missing")
            parts.append(EXECUTION_LABELS.get(state, "执行状态异常：" + state))
        if reason != "unknown":
            parts.append(REASONS.get(reason, reason))

    business = row.get("business")
    if not isinstance(business, Mapping) or not business:
        parts.append("缺少业务状态")
    else:
        incomplete = []
        for name, state in business.items():
            normalized_state = str(state)
            if normalized_state in {"complete", "not_applicable"}:
                continue
            task_name = TASK_LABELS.get(str(name), str(name))
            incomplete.append(
                f"{task_name}{STATE_LABELS.get(normalized_state, normalized_state)}"
            )
        if incomplete:
            parts.append("未完成/未确认事项：" + "、".join(incomplete))

    details = row.get("details")
    items = details.get("items", []) if isinstance(details, Mapping) else []
    if isinstance(items, list):
        uncredited = [
            str(item["name"]).strip()
            for item in items
            if isinstance(item, Mapping)
            and item.get("reason") == "offer_not_credited"
            and str(item.get("name") or "").strip()
        ]
        if uncredited:
            parts.append("积分未确认：" + "、".join(uncredited[:8]))

    return "；".join(parts) if parts else None


def build_report(day: str | None = None) -> str:
    report_day = day or datetime.now(TIMEZONE).date().isoformat()
    date.fromisoformat(report_day)
    problems: list[tuple[str, str]] = []
    for platform, label in TASKS.items():
        row, read_error = load_result(platform)
        if read_error:
            problems.append((label, read_error))
            continue
        assert row is not None
        issue = issue_for(platform, row, report_day)
        if issue:
            problems.append((label, issue))
    if not problems:
        return ""
    lines = [f"福利任务异常告警 {report_day}"]
    lines.extend(f"问题平台：{label}；问题：{issue}" for label, issue in problems)
    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    if report:
        print(report)
