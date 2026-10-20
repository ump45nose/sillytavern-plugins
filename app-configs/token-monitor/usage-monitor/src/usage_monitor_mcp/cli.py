from __future__ import annotations

import argparse
import json

from .config import Settings
from .reports import build_report, summary


def main():
    parser = argparse.ArgumentParser(description="只读核验当天数据；不保存报告、不发送事件")
    parser.add_argument("--date")
    parser.add_argument("--summary", action="store_true", help="显示摘要；默认只显示数据可用性，不打印实际统计")
    args = parser.parse_args()
    report = build_report(Settings.from_env(), args.date)
    if args.summary:
        result = summary(report)
    else:
        result = {"date": report["window"]["date"], "timezone": report["window"]["timezone"],
                  "token_status": report["token_monitor"]["status"],
                  "network_status": report["shellcrash"]["status"],
                  "token_stats_api_status": report["token_monitor"].get("stats_api_status"),
                  "subscriptions_status": report["token_monitor"].get("subscriptions", {}).get("status")}
    print(json.dumps(result, ensure_ascii=False))
