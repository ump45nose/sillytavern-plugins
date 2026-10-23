#!/usr/bin/env python3
"""Print an exception-only report from benefits cron delivery JSON files."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benefits_results import CONFIG, MAX_JSON_BYTES, REASONS, identity_issue, load_deployment


# Telegram per-bot reasons; a captcha or join-channel gate needs the user.
TELEGRAM_BOT_REASONS = {
    "bot_rejected": "被拒绝（验证题或入群门槛），需手动签到",
    "bot_not_started": "未开始对话，需先手动点 START",
    "previous_send_unconfirmed": "已发送但结果未确认，需手动核对",
    "reply_timeout": "未回复",
    "reply_unrecognized": "回复无法识别",
    "button_not_found": "未找到签到按钮",
    "command_not_visible": "命令发送未确认",
    "chat_unavailable": "对话无法打开",
    "input_unconfirmed": "命令输入未确认",
    "send_control_unavailable": "发送按钮不可用",
    "not_attempted": "未执行",
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
    "discovery": "自动发现",
    "app_daily": "APP签到",
    "app_promotions": "APP活动",
    "daily_streaks": "连续打卡",
    "desktop_app_weekly": "桌面APP周任务",
    "balance": "余额查询",
    "points": "积分查询",
    "points_query": "积分查询",
    "activity": "活跃请求",
}
STATE_LABELS = {
    "unknown": "未确认",
    "blocked": "受阻",
    "failed": "失败",
    "busy": "执行中",
    "pending": "待处理",
    "incomplete": "未完成",
}
EXECUTION_LABELS = {
    "failed": "执行失败",
    "busy": "仍在执行",
    "ok": "成功",
}


def load_result(platform: str, delivery_root: Path) -> tuple[dict | None, str | None]:
    path = delivery_root / f"{platform}.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            return None, "结果超过读取限制"
        value = json.loads(raw)
    except FileNotFoundError:
        return None, "未取得当日结果"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "无法读取采集结果"
    if not isinstance(value, dict):
        return None, "结果格式无效"
    return value, None


def issue_for(platform: str, row: Mapping[str, object], day: str) -> str | None:
    mismatch = identity_issue(platform, row, day)
    if mismatch:
        return mismatch

    business = row.get("business")
    if (platform == "workbuddy" and row.get("execution_status") == "ok"
            and row.get("reason") == "activity_sent_reward_unconfirmed"
            and isinstance(business, Mapping)
            and business.get("activity") == "complete"
            and business.get("balance") == "complete"
            and business.get("reward") == "unknown"
            and all(state in ("complete", "not_applicable")
                    for name, state in business.items() if name != "reward")):
        return None

    parts: list[str] = []
    execution = row.get("execution_status")
    reason = str(row.get("reason") or "unknown")
    specific_reason = reason in REASONS and reason != "full_requested_capabilities_partial"
    if specific_reason:
        parts.append(REASONS[reason])
    if execution != "ok":
        if execution == "busy":
            parts.append("任务仍在执行")
        elif not specific_reason:
            state = str(execution or "missing")
            parts.append(EXECUTION_LABELS.get(state, "执行状态异常：" + state))
        if reason not in REASONS and reason != "unknown":
            parts.append(REASONS.get(reason, reason))

    details = row.get("details")
    items = details.get("items", []) if isinstance(details, Mapping) else []
    bot_issues = []
    if platform == "telegram" and isinstance(items, list):
        bot_issues = [
            str(item.get("name") or item.get("id")) + TELEGRAM_BOT_REASONS.get(
                str(item.get("reason")), "未确认（" + str(item.get("reason")) + "）")
            for item in items
            if isinstance(item, Mapping) and item.get("status") not in {"complete", "not_applicable"}
        ]

    if (not isinstance(business, Mapping) or not business) and not specific_reason:
        parts.append("缺少业务状态")
    elif bot_issues and not specific_reason:
        parts.append("、".join(bot_issues[:12]))
    elif isinstance(business, Mapping) and not specific_reason:
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
            parts.append("、".join(incomplete))

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
        if platform == "rewards":
            streaks = [str(item.get("name")) + STATE_LABELS.get(str(item.get("status")), str(item.get("status")))
                       for item in items if isinstance(item, Mapping)
                       and item.get("id") in {"bing_streak", "app_streak"}
                       and item.get("status") not in {"complete", "not_applicable"}]
            if streaks:
                parts.append("、".join(streaks))
            unsupported = [str(item.get("name") or item.get("id")) for item in items
                           if isinstance(item, Mapping) and item.get("reason") == "search_topic_unsupported"]
            if unsupported:
                parts.append("探索主题尚未支持：" + "、".join(unsupported[:8]))
        if platform == "steam":
            token_blocked = sum(isinstance(item, Mapping) and item.get("reason") == "package_token_required"
                                for item in items)
            if token_blocked:
                parts.append(f"{token_blocked} 个候选包缺少访问令牌")
            eligible = [str(item.get("name") or item.get("id")) for item in items
                        if isinstance(item, Mapping) and item.get("reason") == "dry_run_eligible"]
            if eligible:
                parts.append("只读核验合格、待授权领取：" + "、".join(eligible[:8]))
    return "；".join(dict.fromkeys(parts)) if parts else None


def build_report(day: str | None = None) -> str:
    config = load_deployment(CONFIG)
    report_day = day or datetime.now(ZoneInfo(config["timezone"])).date().isoformat()
    date.fromisoformat(report_day)
    delivery_root = Path(config["runtime_root"]) / "delivery"
    tasks = config["tasks"]
    problems: list[tuple[str, str]] = []
    shared_wechat: dict[str, list[str]] = {}
    for task_id, task in tasks.items():
        if task.get("enabled", True) is False:
            continue
        platform = task.get("platform", task_id)
        label = task["label"]
        row, read_error = load_result(task_id, delivery_root)
        if read_error:
            problems.append((label, read_error))
            continue
        assert row is not None
        issue = issue_for(platform, row, report_day)
        if task.get("account") and row.get("account") != task["account"]:
            issue = "结果账号与配置不一致"
        if issue:
            if (platform in {"ole", "yingshijufeng"}
                    and row.get("reason", "").startswith("wechat_code_")
                    and issue == REASONS.get(row.get("reason"))):
                shared_wechat.setdefault(issue, []).append(label)
            else:
                problems.append((label, issue))
    for issue, labels in shared_wechat.items():
        problems.append(("微信取码服务", issue + "（影响：" + "、".join(labels) + "）"))
    if not problems:
        return ""
    lines = ["**福利任务异常**"]
    lines.extend(f"- {label}：{issue}" for label, issue in problems)
    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    if report:
        print(report)
