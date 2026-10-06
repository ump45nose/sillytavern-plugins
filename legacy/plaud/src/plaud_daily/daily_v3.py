"""Hermes no-agent full recording transcription and one-request daily fusion.

Continuous 20-minute ASR blocks cover every recording, including its tail.
Reuses three-source preparation and never invokes CAM/15-minute filtering.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import io
import json
import math
import os
import re
import sys
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import multiday_trial as trial
from .core import RRException, State, atomic_bytes, hash_json, load_config, now_iso
from .sync import parse_utc, sync_local_dir, sync_plaud

DEFAULT_CONFIG = "/vol1/1000/Code/plaud-daily/daily-v3.yaml"


def settings(path: str) -> tuple[dict, dict]:
    workflow = yaml.safe_load(Path(path).read_text())
    if workflow.get("schema_version") != 1 or workflow.get("scope") != "full_recordings":
        raise RuntimeError("Invalid workflow scope")
    if workflow.get("fusion_mode") not in {"review_required", "auto_validated"}:
        raise RuntimeError("Invalid fusion mode")
    config = load_config(workflow["base_config"])
    config["data_root"] = workflow["data_root"]
    config["timezone"] = workflow["timezone"]
    config["plaud_mcp"]["token_file"] = workflow["plaud_token_file"]
    os.environ["GROQ_API_KEY_FILE"] = workflow["groq_key_file"]
    return workflow, config


def dependencies(workflow: dict, config: dict) -> list[str]:
    missing = []
    if config["sync_provider"] == "plaud_mcp":
        token = Path(config["plaud_mcp"]["token_file"])
        if not token.is_file() or token.stat().st_mode & 0o077:
            missing.append("plaud_mcp_login_required")
    if not trial.configured_key("GROQ_API_KEY"):
        missing.append("groq_key_required")
    if not trial.configured_key("CPA_PUBLIC_API_KEY"):
        missing.append("cpa_key_required")
    for name, path in (("sensevoice", config["asr"]["model"]),
                       ("sensevoice_tokens", config["asr"]["tokens"])):
        if not Path(path).is_file() or not os.access(path, os.R_OK):
            missing.append(f"{name}_unreadable")
    return missing


def save_latest(root: Path, result: dict) -> None:
    atomic_bytes(root / "latest.json", (json.dumps({**result, "checked_at": now_iso()}, ensure_ascii=False, indent=2) + "\n").encode())


def source_run(config: dict, workflow: dict, day: str, rows: list[dict]) -> tuple[Path, list[str]]:
    # Changes to source, model, prompt, preparation code or parameters create
    # a separate run instead of reusing stale transcripts or approvals.
    inputs = {"day": day, "recordings": [{"id": r["recording_id"], "audio": r["sha256"], "duration_ms": r["duration_ms"]} for r in rows],
              "asr": config["asr"], "scope": workflow["scope"], "fusion_model": workflow["fusion_model"],
              "gemini_prompt": trial.sha256_file(Path(trial.__file__).with_name("gemini_audio_trial.py")),
              "groq_code": trial.sha256_file(Path(trial.__file__).with_name("groq_whisper_trial.py")),
              "prepare_code": trial.sha256_file(Path(trial.__file__)),
              "runner_code": trial.sha256_file(Path(__file__)),
              "model_hashes": {name: trial.sha256_file(Path(path)) for name, path in
                               (("sensevoice", config["asr"]["model"]),
                                ("tokens", config["asr"]["tokens"]))}}
    run = Path(config["data_root"]) / "runs" / day / hash_json(inputs)[:20]
    run.mkdir(mode=0o750, parents=True, exist_ok=True)
    from .audio import normalize
    chunks = []
    import inspect
    params = {k: v for k, v in inputs.items() if k not in {"day", "recordings", "fusion_model", "runner_code", "prepare_code"}}
    params["sensevoice_inference"] = inspect.getsource(trial.sensevoice)
    for row in rows:
        playable = normalize(row, Path(config["data_root"]))
        duration = row["duration_ms"] / 1000
        if duration <= 0:
            raise RuntimeError("Recording has no audio duration")
        cache = Path(config["data_root"]) / "sources" / row["recording_id"] / hash_json({"sha": row["sha256"], "params": params})[:20]
        for index in range(math.ceil(duration / trial.SECONDS)):
            key = f"{row['recording_id']}-b{index + 1:03d}"
            chunks.append(key)
            folder = cache / key
            folder.mkdir(mode=0o750, parents=True, exist_ok=True)
            target = run / key
            if not target.exists():
                target.symlink_to(folder, target_is_directory=True)
            offset = index * trial.SECONDS
            seconds = min(trial.SECONDS, duration - offset)
            sample_path = folder / "sample.json"
            if sample_path.exists():
                trial.verify_audio(folder)
                continue
            audio = folder / "audio.mp3"
            part = folder / "audio.mp3.part"
            # A prior interrupted extraction is overwritten only inside its
            # own unfinished cache; completed samples are never overwritten.
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "1", "-ss", str(offset),
                            "-i", str(playable), "-t", str(seconds), "-ac", "1", "-ar", "16000",
                            "-b:a", "32k", "-f", "mp3", str(part)], check=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=noprint_wrappers=1:nokey=1", str(part)], capture_output=True, text=True, check=True)
            if abs(float(probe.stdout) - seconds) > 1:
                raise RuntimeError("Continuous ASR block is incomplete")
            os.chmod(part, 0o600)
            os.replace(part, audio)
            local = (parse_utc(row["start_at"]) + timedelta(seconds=offset)).astimezone(ZoneInfo(config["timezone"]))
            sample = {"date": day, "recording_id": row["recording_id"], "source_sha256": row["sha256"],
                      "offset_seconds": offset, "duration_seconds": seconds, "local_excerpt_start": local.isoformat(),
                      "audio_sha256": trial.sha256_file(audio), "asr_language": "zh", "vad_filter": False,
                      "speaker_identity_confirmed": False, "block_index": index + 1}
            trial.write_once(sample_path, json.dumps(sample, ensure_ascii=False, indent=2) + "\n")
    trial.write_once(run / "run-inputs.json", json.dumps(inputs, ensure_ascii=False, indent=2) + "\n")
    return run, chunks


def run_date(workflow: dict, config: dict, day: str, *, skip_sync: bool = False, finalize: bool = True) -> dict:
    root = Path(config["data_root"])
    state = State(root)
    try:
        if not skip_sync:
            if config["sync_provider"] == "local_dir":
                synced = sync_local_dir(config, state, target_date=day)
            else:
                synced = asyncio.run(sync_plaud(config, state, target_date=day))
        else:
            synced = {"status": "explicit_skip_sync"}
        rows = sorted([dict(r) for r in state.recordings_for_date(day) if r["remote_state"] == "downloaded"], key=lambda r: (r["start_at"], r["recording_id"]))
        waiting = [dict(r) for r in state.recordings_for_date(day) if r["remote_state"] != "downloaded"]
        if not rows:
            return {"date": day, "status": "waiting_audio", "sync": synced}
        if waiting:
            return {"date": day, "status": "waiting_audio", "waiting_recordings": len(waiting), "sync": synced}
        run, chunks = source_run(config, workflow, day, rows)
        report_file = run / "review-manifest.json"
        if report_file.is_file():
            report = json.loads(report_file.read_text())
            if trial.sha256_file(run / "fusion-input-multiday-v3.md") != report["input_sha256"]:
                return {"date": day, "status": "review_input_modified", "run": str(run)}
        else:
            # Capture helper diagnostics locally: successful Cron has empty
            # stdout and incurs no Hermes agent invocation.
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                trial.cloud("groq", chunks, root=run)
                if any(not (run / chunk / "groq-whisper-large-v3-summary.json").is_file() for chunk in chunks):
                    atomic_bytes(run / "prepare.log", capture.getvalue().encode())
                    return {"date": day, "status": "source_failed_no_retry", "engine": "groq", "run": str(run)}
                trial.cloud("gemini", chunks, root=run)
                if any(not (run / chunk / "gemini-summary.json").is_file() for chunk in chunks):
                    atomic_bytes(run / "prepare.log", capture.getvalue().encode())
                    return {"date": day, "status": "source_failed_no_retry", "engine": "gemini", "run": str(run)}
                trial.sensevoice(config, chunks, root=run)
                needed = ("groq-whisper-large-v3-summary.json", "gemini-summary.json", "sensevoice-summary.json")
                if any(not (run / chunk / name).is_file() for chunk in chunks for name in needed):
                    atomic_bytes(run / "prepare.log", capture.getvalue().encode())
                    return {"date": day, "status": "source_failed_no_retry", "run": str(run)}
                report = trial.prepare_input(root=run, days=chunks)
            atomic_bytes(run / "prepare.log", capture.getvalue().encode())
        final = run / "transcript-v3.md"
        if not final.exists() and report["eligible_for_submission"] and workflow["fusion_mode"] == "auto_validated" and finalize:
            sent = root / "submissions" / f"{day}.json"
            if sent.exists():
                return {"date": day, "status": "daily_submission_already_attempted", "run": str(run),
                        "detail": "Changed input or interrupted previous request; no automatic second fusion"}
            submit_approved(workflow, run, report["input_sha256"], automatic=True, day=day)
        return {"date": day, "status": "complete" if final.exists() else
                (("waiting_finalize" if workflow["fusion_mode"] == "auto_validated" else "waiting_review") if report["eligible_for_submission"] else "source_quality_blocked"),
                "scope": workflow["scope"], "recordings": len(rows), "blocks": len(chunks), "run": str(run),
                "input": str(run / "fusion-input-multiday-v3.md"), "input_sha256": report["input_sha256"],
                "final": str(final) if final.exists() else None, "waiting_recordings": len(waiting), "sync": synced}
    finally:
        state.close()


def submit_approved(workflow: dict, run: Path, approved: str, *, automatic: bool = False, day: str | None = None) -> dict:
    run = run.resolve()
    if not run.is_relative_to((Path(workflow["data_root"]) / "runs").resolve()):
        raise RuntimeError("Run must reside in the configured daily-v3 run directory")
    report = json.loads((run / "review-manifest.json").read_text())
    input_path = run / "fusion-input-multiday-v3.md"
    if not re.fullmatch(r"[0-9a-f]{64}", approved) or trial.sha256_file(input_path) != approved:
        raise RuntimeError("Reviewed SHA-256 changed; show the current file for review again")
    if not report.get("eligible_for_submission") or approved != report["input_sha256"]:
        raise RuntimeError("Source validation failed or the manifest no longer matches the approved input")
    contents = input_path.read_text()
    if len(contents.encode()) > workflow["max_input_bytes"]:
        raise RuntimeError("Input exceeds the single-request limit; no splitting or request sent")
    key = trial.configured_key("CPA_PUBLIC_API_KEY")
    if not key:
        raise RuntimeError("CPA credential required")
    sentinel = run / "submission-attempt.json"
    body = {"model": workflow["fusion_model"], "temperature": 0, "max_tokens": 48000,
            "messages": [{"role": "user", "content": contents}]}
    status = {"approved_sha256": approved, "model": workflow["fusion_model"], "status": "attempted_once",
              "approval_kind": "automatic_source_validation" if automatic else "explicit_hash_approval"}
    if automatic:
        if not day:
            raise RuntimeError("Date required for automatic daily submission")
        fence = Path(workflow["data_root"]) / "submissions" / f"{day}.json"
        fence.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        with fence.open("x") as stream:
            os.chmod(fence, 0o600)
            json.dump({**status, "run": str(run)}, stream)
            stream.flush()
            os.fsync(stream.fileno())
    # O_EXCL is the process-safe at-most-one request fence; a timeout is never
    # treated as permission to submit a second time.
    with sentinel.open("x") as stream:
        os.chmod(sentinel, 0o600)
        json.dump(status, stream)
        stream.flush()
        os.fsync(stream.fileno())
    request = urllib.request.Request(workflow["cpa_url"], data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
        choice = result["choices"][0]
        answer = choice["message"]["content"]
        if choice.get("finish_reason") != "stop" or not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Incomplete response")
        trial.write_once(run / "response-unvalidated.md", answer.rstrip() + "\n")
        if "【他人?】" in answer or not re.search(r"\[\d{2}:\d{2}\]", answer):
            raise RuntimeError("Output has invalid identity or lacks timestamps")
        inventory = json.loads((run / "run-inputs.json").read_text())["recordings"]
        if any(r["id"] not in answer for r in inventory):
            raise RuntimeError("Output omitted at least one recording; no final published")
        footer = f"\n\n---\n输入 SHA-256：`{approved}`；模型：`{result.get('model', workflow['fusion_model'])}`；用量：`{json.dumps(result.get('usage'), ensure_ascii=False)}`；耗时：{time.monotonic()-started:.1f} 秒。\n"
        trial.write_once(run / "transcript-v3.md", answer.rstrip() + footer)
        status.update(status="complete", usage=result.get("usage"), elapsed_seconds=round(time.monotonic()-started, 2))
    except Exception as error:
        detail = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else str(error).replace(key, "<redacted>")[:300]
        status.update(status="failed", error=detail)
        trial.write_status(sentinel, status)
        if automatic:
            trial.write_status(fence, {**status, "run": str(run)})
        raise RuntimeError(f"Single request failed; no retry: {detail}") from None
    trial.write_status(sentinel, status)
    if automatic:
        trial.write_status(fence, {**status, "run": str(run)})
    output = Path(workflow["data_root"]) / "output" / f"{day or run.parent.name}.md"
    atomic_bytes(output, (run / "transcript-v3.md").read_bytes())
    return {"status": "complete", "final": str(run / "transcript-v3.md"), "input_sha256": approved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run-date")
    run.add_argument("--date", type=date.fromisoformat)
    run.add_argument("--skip-sync", action="store_true", help="Manual local smoke only; not used by Cron")
    run.add_argument("--cron", action="store_true", help="Silence successful/waiting output")
    sub.add_parser("doctor")
    sub.add_parser("login", help="Interactive Plaud MCP OAuth as the runtime account; never invoked by Cron")
    submit = sub.add_parser("submit-approved")
    submit.add_argument("--run", type=Path, required=True)
    submit.add_argument("--approved-sha256", required=True)
    args = parser.parse_args()
    try:
        workflow, config = settings(args.config)
        root = Path(config["data_root"])
        root.mkdir(parents=True, exist_ok=True, mode=0o750)
        lock = root / "daily-v3.lock"
        with lock.open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if not getattr(args, "cron", False):
                    print(json.dumps({"status": "skipped_locked"}))
                return 0
            if args.command == "doctor":
                missing = dependencies(workflow, config)
                result = {"status": "blocked_credentials" if missing else "ready", "missing": missing,
                          "scope": workflow["scope"], "fusion_mode": workflow["fusion_mode"]}
            elif args.command == "login":
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client

                async def login():
                    params = StdioServerParameters(command=config["plaud_mcp"]["command"], args=config["plaud_mcp"]["args"])
                    async with stdio_client(params) as (reader, writer):
                        async with ClientSession(reader, writer) as session:
                            await session.initialize()
                            response = await session.call_tool("login", {}, read_timeout_seconds=180)
                            return {"status": "login_failed" if response.isError else "logged_in",
                                    "message": "\n".join(getattr(block, "text", "") for block in response.content)}

                print("Plaud OAuth will open a browser; remote clients must forward port 8199 before login.", file=sys.stderr)
                result = asyncio.run(login())
            elif args.command == "submit-approved":
                result = submit_approved(workflow, args.run, args.approved_sha256)
            else:
                day = (args.date or (datetime.now(ZoneInfo(workflow["timezone"])).date() - timedelta(days=1))).isoformat()
                missing = dependencies(workflow, config)
                if args.skip_sync:
                    missing = [m for m in missing if m != "plaud_mcp_login_required"]
                local_now = datetime.now(ZoneInfo(workflow["timezone"]))
                finalize = not args.cron or local_now.hour * 60 + local_now.minute >= 450
                result = {"date": day, "status": "blocked_credentials", "missing": missing} if missing else run_date(workflow, config, day, skip_sync=args.skip_sync, finalize=finalize)
            save_latest(root, result)
            failed = result["status"] in {"blocked_credentials", "source_failed_no_retry", "source_quality_blocked", "review_input_modified", "daily_submission_already_attempted", "login_failed"}
            if not getattr(args, "cron", False) or failed:
                print(json.dumps(result, ensure_ascii=False))
            return 2 if failed else 0
    except Exception as error:
        result = {"status": "failed", "error": error.code if isinstance(error, RRException) else type(error).__name__,
                  "detail": str(error)[:300] if isinstance(error, (RuntimeError, RRException, FileExistsError)) else "Inspect local runtime prerequisites"}
        if "root" in locals():
            try:
                save_latest(root, result)
            except OSError:
                pass
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
