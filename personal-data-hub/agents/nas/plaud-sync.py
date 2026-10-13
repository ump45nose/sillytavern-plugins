"""保留 Plaud SDK 2.x 的独立环境，只执行官方下载阶段。"""
import asyncio
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "collectors/plaud/src"))
from plaud_collection.core import State, load_config
from plaud_collection.sync import sync_plaud

config = load_config(str(Path.home() / ".config/personal-data-hub/plaud.yaml"))
config["archive_only"] = True
state = State(Path(config["data_root"]))
try:
    result = asyncio.run(sync_plaud(config, state))
    print({"status": "ok", **result})
finally:
    state.close()
