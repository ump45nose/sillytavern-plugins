"""Import the real optional SDK with its dependency directory read-only."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from platforms.epic.native import build_challenge

with tempfile.TemporaryDirectory() as directory:
    os.environ["TMPDIR"] = directory
    handler = build_challenge(object(), {"model": {"name": "fixture", "api_key": "fixture"}})
    assert handler.agent is None
    from loguru import logger
    assert not logger._core.handlers
    print("PASS: real SDK initializes without package log writes, logging sinks or model requests")
