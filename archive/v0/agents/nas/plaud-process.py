"""Plaud 转录、融合日报和摘要入口，保留既有独立运行环境及凭据。"""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
package = root / "processors/plaud/src"
sys.path.insert(0, str(package))
os.environ["PYTHONPATH"] = str(package) + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")

from plaud_daily.daily_v3 import main

raise SystemExit(main())
