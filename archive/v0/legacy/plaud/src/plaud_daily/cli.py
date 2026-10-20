"""Independently runnable business commands for Plaud daily transcripts."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import resource
import sys
import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import RRException, State, data_root, load_config
from .processing import enroll, preprocess, transcribe
from .render import render, render_recording
from .sync import sync_local_dir, sync_plaud


def _date(value: str) -> str:
    try:
        return Date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recording-review")
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync")
    sync.add_argument("--date", type=_date)
    sync.add_argument("--recording-id")
    sync.add_argument("--dry-run", action="store_true")
    for name in ("preprocess", "asr"):
        sub.add_parser(name).add_argument("--recording-id", required=True)
    sub.add_parser("render").add_argument("--date", required=True, type=_date)
    sub.add_parser("render-recording").add_argument("--recording-id", required=True)
    sub.add_parser("run-date").add_argument("--date", type=_date)
    enrollment = sub.add_parser("enroll")
    enrollment.add_argument("--input", type=Path, required=True)
    retry = sub.add_parser("retry")
    retry.add_argument("--recording-id", required=True)
    retry.add_argument("--from-stage", choices=("sync", "preprocess", "asr"), default="sync")
    inspection = sub.add_parser("inspect")
    group = inspection.add_mutually_exclusive_group()
    group.add_argument("--recording-id")
    group.add_argument("--date", type=_date)
    return parser


def _sync(config: dict, state: State | None, date: str | None = None, recording_id: str | None = None, dry_run: bool = False) -> dict:
    if config["sync_provider"] == "plaud_mcp":
        return asyncio.run(sync_plaud(config, state, target_date=date, recording_id=recording_id, dry_run=dry_run))
    if config["sync_provider"] == "local_dir":
        if recording_id:
            raise RRException("unsupported_option", "local_dir sync selects by date, not id")
        return sync_local_dir(config, state, target_date=date, dry_run=dry_run)
    raise RRException("provider_unsupported", "Only plaud_mcp and local_dir are supported")


def _run_date(config: dict, state: State, date: str) -> dict:
    root = data_root(config)
    lock = root / "locks/run-date.lock"
    with lock.open("w") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"date": date, "status": "skipped_locked"}
        started = time.monotonic()
        sync_result = _sync(config, state, date=date)
        stage_result = []
        rows = state.recordings_for_date(date)
        for row in rows:
            if row["remote_state"] != "downloaded":
                continue
            stage_result.append({"preprocess": preprocess(config, state, row["recording_id"])})
        for row, stage in zip([item for item in rows if item["remote_state"] == "downloaded"], stage_result):
            stage["asr"] = transcribe(config, state, row["recording_id"])
        result = render(config, state, date)
        return {"date": date, "status": "done", "sync": sync_result, "stages": stage_result, "render": result, "elapsed_seconds": round(time.monotonic() - started, 2), "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def _inspect(state: State, recording_id: str | None, date: str | None) -> dict:
    if recording_id:
        rows = state.conn.execute("SELECT * FROM recordings WHERE recording_id=?", (recording_id,)).fetchall()
        stages = state.conn.execute("SELECT * FROM stage_runs WHERE scope_type='recording' AND scope_id=? ORDER BY id", (recording_id,)).fetchall()
    elif date:
        rows = state.recordings_for_date(date)
        stages = state.conn.execute("SELECT * FROM stage_runs WHERE (scope_type='date' AND scope_id=?) OR (scope_type='recording' AND scope_id IN (SELECT recording_id FROM recordings WHERE local_date=?)) ORDER BY id", (date, date)).fetchall()
    else:
        rows = state.conn.execute("SELECT * FROM recordings ORDER BY start_at DESC LIMIT 50").fetchall()
        stages = state.conn.execute("SELECT * FROM stage_runs ORDER BY id DESC LIMIT 100").fetchall()
    return {"recordings": [dict(row) for row in rows], "stages": [dict(row) for row in stages]}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "sync" and args.dry_run:
            result = _sync(config, None, date=args.date, recording_id=args.recording_id, dry_run=True)
            print(json.dumps({"ok": True, **result}, ensure_ascii=False, separators=(",", ":")))
            return 0
        state = State(data_root(config))
        try:
            if args.command == "sync":
                result = _sync(config, state, date=args.date, recording_id=args.recording_id, dry_run=args.dry_run)
            elif args.command == "preprocess":
                result = preprocess(config, state, args.recording_id)
            elif args.command == "asr":
                result = transcribe(config, state, args.recording_id)
            elif args.command == "render":
                result = render(config, state, args.date)
            elif args.command == "render-recording":
                result = render_recording(config, state, args.recording_id)
            elif args.command == "run-date":
                target = args.date or (datetime.now(ZoneInfo(config["timezone"])).date() - timedelta(days=1)).isoformat()
                result = _run_date(config, state, target)
            elif args.command == "enroll":
                result = enroll(config, args.input)
            elif args.command == "retry":
                if args.from_stage == "sync":
                    _sync(config, state, recording_id=args.recording_id)
                if args.from_stage in ("sync", "preprocess"):
                    preprocess(config, state, args.recording_id)
                result = transcribe(config, state, args.recording_id)
            else:
                result = _inspect(state, args.recording_id, args.date)
        finally:
            state.close()
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, separators=(",", ":")))
        return 0
    except RRException as exc:
        print(json.dumps({"ok": False, "error_code": exc.code, "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        return exc.exit_code
    except ExceptionGroup as group:
        def first_error(error):
            if isinstance(error, RRException):
                return error
            if isinstance(error, BaseExceptionGroup):
                for child in error.exceptions:
                    match = first_error(child)
                    if match:
                        return match
            return None
        error = first_error(group)
        if error:
            print(json.dumps({"ok": False, "error_code": error.code, "error": str(error)}, ensure_ascii=False, separators=(",", ":")))
            return error.exit_code
        print(json.dumps({"ok": False, "error_code": "mcp_transport_error", "error": str(group)[:200]}, ensure_ascii=False, separators=(",", ":")))
        return 3
    except Exception as exc:
        print(json.dumps({"ok": False, "error_code": "unexpected_error", "error": str(exc)[:200]}, ensure_ascii=False, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    sys.exit(main())
