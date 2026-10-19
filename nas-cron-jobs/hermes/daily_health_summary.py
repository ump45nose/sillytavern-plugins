#!/usr/bin/env python3
"""Query daily business metrics; all aggregation belongs to Personal Records."""
import argparse
from datetime import datetime
import json
from zoneinfo import ZoneInfo
from personal_records.client import RecordsClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--start-date", default=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
    parser.add_argument("--end-date")
    args = parser.parse_args()
    print(json.dumps(RecordsClient.from_file(args.config).health_summary(args.start_date, args.end_date or args.start_date), ensure_ascii=False))


if __name__ == "__main__": main()
