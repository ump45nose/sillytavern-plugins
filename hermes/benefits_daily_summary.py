#!/usr/bin/env python3
"""Read native delivery JSON; Hermes owns scheduling and notification."""
import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from benefits_native_runner import CONFIG, bounded

REASONS = {
    "authentication_invalid": "登录失效", "human_required": "遇到验证",
    "launcher_failed": "启动失败", "deadline_exceeded": "执行超时",
    "configuration_or_io_error": "配置或结果保存失败", "lock_busy": "已有任务执行中",
    "native_configuration_or_browser_error": "Epic 配置或浏览器异常",
    "full_intervention_pending": "微软任务遇到验证或登录问题",
    "steam_login_required": "Steam 需要首次登录或恢复会话",
    "steam_account_mismatch": "Steam 账号身份不匹配",
    "private_file_unreadable": "Steam 私有配置未准备完成",
    "discovery_coverage_incomplete": "自动发现覆盖不完整",
    "discovery_candidates_require_review": "候选证据需要核对",
}


def fmt(value):
    if value is None:
        return "未知"
    return str(int(value)) if float(value).is_integer() else str(round(value, 2))


def describe(platform, row):
    business = row.get("business", {})
    metrics = row.get("details", {}).get("metrics", {})
    items = row.get("details", {}).get("items", [])
    execution = row.get("execution_status")
    good = [key for key, state in business.items() if state == "complete"]
    pending = [state for state in business.values() if state not in {"complete", "not_applicable"}]
    status = ("未执行" if execution == "busy" else "失败" if execution != "ok" else
              "部分完成" if pending and good else "未完成" if pending else
              "不适用" if not good else "成功")
    if platform == "smzdm" and business.get("checkin") == "complete":
        status = "签到成功" + ("；奖励未确认" if business.get("reward") == "unknown" else "")
    parts = []
    if execution != "ok":
        reason = row.get("reason", "unknown")
        parts.append(REASONS.get(reason, reason))
    def count(key):
        return fmt(metrics.get(key, {}).get("current"))
    def progress(key, label):
        m = metrics.get(key, {})
        parts.append(label + " " + fmt(m.get("current")) + "/" + fmt(m.get("max")))
    if platform == "rewards":
        for key, label in [("daily", "每日活动"), ("desktop_search", "电脑搜索"),
                           ("app_daily", "APP签到"), ("explore", "探索必应")]:
            progress(key, label)
        parts.append("本次余额变动 " + fmt(metrics.get("balance", {}).get("delta")) + " 分")
        names = [x["name"] for x in items if x.get("reason") == "offer_not_credited"]
        if names:
            parts.append("积分未确认：" + "、".join(names[:8]))
        if metrics.get("locked_tasks", {}).get("current"):
            parts.append("锁定 " + count("locked_tasks") + " 项")
        if metrics.get("balance", {}).get("after") is None and metrics.get("balance", {}).get("before") is not None:
            parts.append("进度为本次已核实值；结束读回未确认")
    elif platform == "epic":
        parts += ["新领 " + count("newly_claimed") + " 款", "已在库 " + count("already_owned") + " 款",
                  "未确认 " + count("unconfirmed") + " 款"]
        for key, label in [("newly_claimed", "新领取"), ("already_owned", "已在库")]:
            names = [x["name"] for x in items if x.get("reason") == key]
            if names:
                parts.append(label + "：" + "、".join(names[:12]))
    elif platform == "steam":
        parts += ["核验候选 " + count("discovered_packages") + " 个",
                  "新领 " + count("claimed_packages") + " 个包"]
        eligible = [x["name"] for x in items if x.get("reason") == "dry_run_eligible"]
        owned = [x["name"] for x in items if x.get("reason") in {
            "owned_package_verified", "previous_submission_owned_verified"}]
        if eligible:
            parts.append("只读核验合格、待授权领取：" + "、".join(eligible[:12]))
        if owned:
            parts.append("已拥有：" + "、".join(owned[:12]))
        if business.get("discovery") != "complete":
            parts.append("发现覆盖或候选证据未确认")
    elif platform == "laowang":
        parts += ["奖励 " + count("reward"), "连续 " + count("streak") + " 天"]
    elif platform == "aliyun":
        parts.append("本次余额变动 " + fmt(metrics.get("balance", {}).get("delta")) + " 分")
    elif platform == "v2ex":
        parts.append("连续 " + count("streak") + " 天")
    return status + ("（" + "；".join(parts) + "）" if parts else "")


def render(day):
    cfg = bounded(CONFIG)
    root = Path(cfg["runtime_root"]) / "delivery"
    lines = [f"每日签到结果 {day}"]
    for platform, task in cfg["tasks"].items():
        try:
            row = bounded(root / (platform + ".json"))
            if (row.get("business_date") != day or row.get("platform") != platform
                    or row.get("account") != task["account"]):
                row = None
        except (OSError, ValueError, TypeError):
            row = None
        lines.append(task["label"] + "：" + (describe(platform, row) if row else "未执行（无当日结果）"))
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    args = parser.parse_args()
    day = args.date or datetime.now(ZoneInfo(bounded(CONFIG)["timezone"])).date().isoformat()
    datetime.strptime(day, "%Y-%m-%d")
    print(render(day))
