#!/usr/bin/env python3
"""把 Mac 上已经闭合的 Skysight 片段幂等同步到 NAS。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any
from zoneinfo import ZoneInfo


DEFAULT_SOURCE = Path(
    "/Users/yuwk/Library/Group Containers/2DC432GLL2.com.openai.sky.CUAService/"
    "Library/Caches/ComputerUse/Skysight/segments"
)
DEFAULT_CHECKPOINT = Path(
    "/Users/yuwk/Library/Application Support/PersonalReview/skysight-checkpoint.json"
)


def _arguments() -> argparse.Namespace:
    """解析同步参数；默认只传输闭合片段。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--host", default="nas")
    parser.add_argument("--target", default="/vol2/1000/Docker/personal-review/data/raw/skysight")
    parser.add_argument("--derived-source", type=Path, default=Path("/Users/yuwk/.codex/memories/extensions/skysight/resources"))
    parser.add_argument("--derived-target", default="/vol2/1000/Docker/personal-review/data/derived/skysight/source-summaries")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def _load_checkpoint(path: Path) -> dict[str, Any]:
    """读取本地 checkpoint；坏文件直接失败而非从头重复同步。"""

    if not path.exists():
        return {"schema_version": 1, "segments": {}, "summaries": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("segments"), dict):
        raise ValueError("checkpoint 结构不兼容")
    data.setdefault("summaries", {})
    return data


def _save_checkpoint(path: Path, data: dict[str, Any]) -> None:
    """原子保存 checkpoint，避免中断造成半写文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _digest(paths: list[Path]) -> str:
    """计算片段文件组合哈希，支持闭合后修正重传。"""

    hasher = hashlib.sha256()
    for path in paths:
        hasher.update(path.name.encode())
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def _validate_segment(directory: Path) -> tuple[dict[str, Any], str] | None:
    """校验片段已闭合且 JSONL 行数与 metadata 一致。"""

    metadata_path = directory / "metadata.json"
    events_path = directory / "events.jsonl"
    if not metadata_path.is_file() or not events_path.is_file():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("endedAt") is None:
        return None
    expected = metadata.get("eventCount")
    actual = 0
    with events_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{directory.name}/events.jsonl:{line_number} 坏 JSON") from exc
            actual += 1
    if isinstance(expected, int) and expected != actual:
        raise ValueError(f"{directory.name} eventCount={expected}，实际={actual}")
    return metadata, _digest([metadata_path, events_path])


def _run(command: list[str], dry_run: bool) -> None:
    """执行无 shell 拼接的 SSH/rsync 命令，dry-run 只打印 JSON。"""

    if dry_run:
        print(json.dumps({"dry_run": command}, ensure_ascii=False))
        return
    subprocess.run(command, check=True)


def _sync_segment(args: argparse.Namespace, directory: Path, metadata: dict[str, Any]) -> None:
    """按片段起始事件的业务日期复制，并延迟提交每个更新文件。"""

    timezone = ZoneInfo(args.timezone)
    started = datetime.fromisoformat(str(metadata["startedAt"]).replace("Z", "+00:00"))
    day = started.astimezone(timezone).date().isoformat()
    final = f"{args.target}/{day}/{directory.name}"
    if not directory.name.endswith("Z") or "/raw/skysight" not in args.target:
        raise ValueError("拒绝使用不安全的片段名或 NAS 目标")
    _run(["ssh", args.host, "mkdir", "-p", f"{args.target}/{day}"], args.dry_run)
    _run(["rsync", "-a", "--delay-updates", f"{directory}/", f"{args.host}:{final}/"], args.dry_run)


def _sync_summaries(args: argparse.Namespace, checkpoint: dict[str, Any]) -> int:
    """增量同步 Computer History 已生成的 10 分钟和 6 小时摘要。"""

    if not args.derived_source.is_dir():
        return 0
    changed = 0
    for path in sorted(args.derived_source.glob("*-memory-summary.md")):
        if "10min" not in path.name and "6h" not in path.name:
            continue
        digest = _digest([path])
        if checkpoint["summaries"].get(path.name) == digest:
            continue
        _run(["ssh", args.host, "mkdir", "-p", args.derived_target], args.dry_run)
        _run(["rsync", "-a", str(path), f"{args.host}:{args.derived_target}/{path.name}"], args.dry_run)
        if not args.dry_run:
            checkpoint["summaries"][path.name] = digest
        changed += 1
    return changed


def main() -> int:
    """先同步日报摘要，再扫描闭合片段并记录可恢复的局部失败。"""

    args = _arguments()
    checkpoint = _load_checkpoint(args.checkpoint)
    synced = 0
    skipped_mutable = 0
    segment_errors = 0

    # 日报消费的是上游摘要；raw 中的单个坏片段或 TCC 权限不能阻断摘要同步。
    summaries = _sync_summaries(args, checkpoint)
    if not args.dry_run:
        checkpoint["last_summary_success_at"] = datetime.now().astimezone().isoformat()
        _save_checkpoint(args.checkpoint, checkpoint)

    try:
        directories = sorted(path for path in args.source.iterdir() if path.is_dir())
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "partial",
                    "segments_synced": synced,
                    "mutable_skipped": skipped_mutable,
                    "segment_errors": 1,
                    "summaries_synced": summaries,
                    "raw_error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2

    for directory in directories:
        try:
            result = _validate_segment(directory)
            if result is None:
                skipped_mutable += 1
                continue
            metadata, digest = result
            if checkpoint["segments"].get(directory.name) == digest:
                continue
            _sync_segment(args, directory, metadata)
            if not args.dry_run:
                checkpoint["segments"][directory.name] = digest
                _save_checkpoint(args.checkpoint, checkpoint)
            synced += 1
        except (OSError, ValueError, subprocess.CalledProcessError):
            # 坏片段保留在源端等待修复；不得删除，也不得阻断其他闭合片段。
            segment_errors += 1

    if not args.dry_run:
        checkpoint["last_success_at"] = datetime.now().astimezone().isoformat()
        _save_checkpoint(args.checkpoint, checkpoint)
    status = "partial" if segment_errors else "ok"
    print(
        json.dumps(
            {
                "status": status,
                "segments_synced": synced,
                "mutable_skipped": skipped_mutable,
                "segment_errors": segment_errors,
                "summaries_synced": summaries,
            },
            ensure_ascii=False,
        )
    )
    return 2 if segment_errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
