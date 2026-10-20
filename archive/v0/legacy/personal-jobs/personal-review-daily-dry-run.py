#!/usr/bin/env python3
"""每天生成但不投递日报材料包，供三日噪声验收。"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys


APP_ROOT = Path(os.environ.get("REVIEW_APP_ROOT", "/vol2/1000/Docker/personal-review"))
REVIEWCTL = APP_ROOT / "bin/reviewctl"
sys.path.insert(0, str(APP_ROOT))

from review.config import load_config  # noqa: E402


def main() -> int:
    """调用 prepare 并把完整 JSON 原子保存为按日验收工件。"""

    config = load_config(APP_ROOT / ".env", APP_ROOT / "config/review.yaml")
    day = datetime.now(config.timezone).date().isoformat()
    process = subprocess.run(
        [str(REVIEWCTL), "daily", "prepare", "--date", day],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if process.returncode != 0:
        print(process.stderr.strip() or json.dumps({"status": "error", "message": "daily dry-run failed"}, ensure_ascii=False))
        return process.returncode
    # 确认输出是 JSON 后再写，避免把截断结果计为成功样本。
    json.loads(process.stdout)
    directory = APP_ROOT / "artifacts/dry-run/daily"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{day}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(process.stdout, encoding="utf-8")
    temporary.replace(target)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "type": type(exc).__name__, "message": str(exc)[:300]}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
