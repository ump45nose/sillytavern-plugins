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
    "steam": "Steam 限免",
}
REASONS = {
    "authentication_invalid": "登录失效",
    "authentication_unconfirmed": "登录状态无法确认",
    "cookiecloud_auth_pair_incomplete": "登录 Cookie 不完整，需重新登录并同步",
    "cart_preserved": "购物车状态无法确认，领取已停止",
    "full_requested_capabilities_partial": "已启用任务部分未完成",
    "full_task_cycle_changed": "平台任务已重置，需核查新一轮",
    "human_required": "需要人工验证",
    "launcher_failed": "启动失败",
    "deadline_exceeded": "执行超时",
    "configuration_or_io_error": "配置或结果保存失败",
    "lock_busy": "已有任务执行中",
    "native_configuration_or_browser_error": "配置或浏览器异常",
    "store_assets_access_denied": "商店资源被拒绝访问（403），领取已停止",
    "challenge_timeout": "验证码处理超时",
    "challenge_unconfirmed": "验证码未通过",
    "product_state_unconfirmed": "商品页状态未确认",
    "checkout_state_unconfirmed": "结算页状态未确认",
    "full_intervention_pending": "遇到验证或登录问题",
    "steam_login_required": "需要首次登录或恢复 Steam 会话",
    "steam_account_mismatch": "Steam 账号身份不匹配",
    "private_file_unreadable": "Steam 登录配置无法读取",
    "ipc_authentication_failed": "ASF IPC 认证失败",
    "ipc_transport_uncertain": "ASF IPC 连接未确认",
    "private_file_permissions_or_size": "Steam 私有配置权限不符合要求",
    "discovery_coverage_incomplete": "自动发现覆盖不完整",
    "discovery_candidates_require_review": "候选证据需要核对",
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
MAX_JSON_BYTES = 65536


def load_result(platform: str) -> tuple[dict | None, str | None]:
    path = DELIVERY_ROOT / f"{platform}.json"
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
    if row.get("platform") != platform:
        return "结果平台标识与文件名不一致"
    if row.get("business_date") != day:
        found = row.get("business_date") or "未知"
        return f"缺少当日结果（最新结果日期：{found}）"

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

    business = row.get("business")
    if (not isinstance(business, Mapping) or not business) and not specific_reason:
        parts.append("缺少业务状态")
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
        if platform == "rewards":
            streaks = [str(item.get("name")) + STATE_LABELS.get(str(item.get("status")), str(item.get("status")))
                       for item in items if isinstance(item, Mapping)
                       and item.get("id") in {"bing_streak", "daily_set_streak", "app_streak"}
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
    generated_at = datetime.now(TIMEZONE)
    report_day = day or generated_at.date().isoformat()
    date.fromisoformat(report_day)
    problems: list[tuple[str, str]] = []
    # Disabled tasks retain their old results but no longer produce missing or
    # failed-result alerts. Unreadable configuration must still fail visibly.
    deployment_path = DELIVERY_ROOT.parents[1] / "benefits-deployment.json"
    disabled = set()
    if deployment_path.exists():
        with deployment_path.open("rb") as stream:
            raw = stream.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise ValueError("benefits deployment configuration exceeds read limit")
        config = json.loads(raw)
        disabled = {name for name, task in config["tasks"].items()
                    if task.get("enabled", True) is False}
    for platform, label in TASKS.items():
        if platform in disabled:
            continue
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
    lines = ["**福利任务异常**"]
    lines.extend(f"- {label}：{issue}" for label, issue in problems)
    return "\n".join(lines)


if __name__ == "__main__":
    report = build_report()
    if report:
        print(report)
