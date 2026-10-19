#!/usr/bin/env python3
"""Read only the published Skysight archive as its owner; request contains no paths."""
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

SOURCE = Path("/vol1/1000/Code/personal-info")
sys.path[:0] = [str(SOURCE / "personal-review"), str(SOURCE / "personal-records/src")]
from review.domain import TimeWindow
from review.sources.skysight import SkysightSummarySource

if __name__ == "__main__":
    request = json.load(sys.stdin)
    window = TimeWindow(datetime.fromisoformat(request["start"]), datetime.fromisoformat(request["end"]))
    result = SkysightSummarySource("/home/yuwk/.codex/skysight-sync").collect(window, request.get("checkpoint"))
    print(json.dumps(asdict(result), ensure_ascii=False, default=lambda value: value.isoformat()))
