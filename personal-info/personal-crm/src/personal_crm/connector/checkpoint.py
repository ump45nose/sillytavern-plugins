"""可恢复的本地 checkpoint。"""

import json
import os
import tempfile
from pathlib import Path


def load(path: str) -> dict:
    """读取 checkpoint；仅不存在时从空状态开始，其他读取错误直接暴露。"""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("checkpoint_invalid")
        return value
    except FileNotFoundError:
        return {}


def save(path: str, value: dict) -> None:
    """通过同目录临时文件 + replace 原子写入 checkpoint。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
