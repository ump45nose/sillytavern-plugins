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
import sqlite3
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

DEFAULT_CONFIG = "/home/yuwk/.config/personal-data-hub/plaud-processing.yaml"


def settings(path: str) -> tuple[dict, dict]:
    workflow = yaml.safe_load(Path(path).read_text())
    if workflow.get("schema_version") != 1 or workflow.get("scope") != "full_recordings":
        raise RuntimeError("Invalid workflow scope")
    if workflow.get("fusion_mode") not in {"review_required", "auto_validated"}:
        raise RuntimeError("Invalid fusion mode")
    config = load_config(workflow["base_config"])
    config['archive_data_root'] = config['data_root']
    config["data_root"] = workflow["data_root"]
    config["timezone"] = workflow["timezone"]
    config["plaud_mcp"]["token_file"] = workflow["plaud_token_file"]
    os.environ["GROQ_API_KEY_FILE"] = workflow["groq_key_file"]
    os.environ["PLAUD_GEMINI_MODEL"] = workflow.get("gemini_model", "gemini-3-flash")
    os.environ["PLAUD_CPA_URL"] = workflow["cpa_url"]
    os.environ["PLAUD_GEMINI_TRANSPORT"] = workflow.get("gemini_transport", "chat")
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
    content = (json.dumps({**result, "checked_at": now_iso()}, ensure_ascii=False, indent=2) + "\n").encode()
    atomic_bytes(root / "latest.json", content)
    if result.get("date"):
        atomic_bytes(root / "status" / f"{result['date']}.json", content)


def source_run(config: dict, workflow: dict, day: str, rows: list[dict]) -> tuple[Path, list[str]]:
    # Changes to source, model, prompt, preparation code or parameters create
    # a separate run instead of reusing stale transcripts or approvals.
    inputs = {"day": day, "recordings": [{"id": r["recording_id"], "audio": r["sha256"], "duration_ms": r["duration_ms"]} for r in rows],
              "asr": config["asr"], "scope": workflow["scope"], "fusion_model": workflow["fusion_model"],
              "gemini_prompt": trial.sha256_file(Path(trial.__file__).with_name("gemini_audio_trial.py")),
              "groq_code": trial.sha256_file(Path(trial.__file__).with_name("groq_whisper_trial.py")),
              "prepare_code": trial.sha256_file(Path(trial.__file__)),
              "runner_code": trial.sha256_file(Path(__file__)), "gemini_model": workflow.get("gemini_model", "gemini-3-flash"),
              "gemini_transport": workflow.get("gemini_transport", "chat"),
              "gemini_native_code": trial.sha256_file(Path(trial.__file__).with_name("gemini_native.py")) if workflow.get("gemini_transport") == "native" else None,
              "model_hashes": {name: trial.sha256_file(Path(path)) for name, path in
                               (("sensevoice", config["asr"]["model"]),
                                ("tokens", config["asr"]["tokens"]))}}
    run = Path(config["data_root"]) / "runs" / day / hash_json(inputs)[:20]
    run.mkdir(mode=0o750, parents=True, exist_ok=True)
    from .audio import normalize
    chunks = []
    import inspect
    params = {k: v for k, v in inputs.items() if k not in {"day", "recordings", "fusion_model", "runner_code", "prepare_code", "gemini_model", "gemini_transport", "gemini_native_code"}}
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


def draft_report(workflow, run, chunks, day):
    """完整单源稿独立可读；不替代缺失来源的三源融合门禁。"""
    inventory = json.loads((run / "run-inputs.json").read_text())["recordings"]
    lines = [f"# Plaud 录音日报草稿 · {day}", "", "> 完整 Groq 单源稿；三源融合尚未完成，文字与关键事实待核对。", ""]
    for recording in inventory:
        lines += ["## 录音 " + recording["id"], ""]
        for chunk in chunks:
            folder = run / chunk
            sample = json.loads((folder / "sample.json").read_text())
            if sample["recording_id"] != recording["id"]: continue
            report = json.loads((folder / "groq-whisper-large-v3-summary.json").read_text())
            source = json.loads((folder / "groq-whisper-large-v3.json").read_text())
            if report["audio_sha256"] != trial.verify_audio(folder) or abs(float(source.get("duration", 0)) - sample["duration_seconds"]) > 1:
                raise RuntimeError("Draft source hash or coverage mismatch")
            lines += [f"[{trial.stamp(sample['offset_seconds'] + float(s['start']))}] {s['text']}" for s in source["segments"]]
        lines.append("")
    atomic_bytes(run / "draft-transcript.md", "\n".join(lines).encode())
    atomic_bytes(Path(workflow["data_root"]) / "output" / f"{day}.draft.md", (run / "draft-transcript.md").read_bytes())
    from .summary import summarize
    return summarize(workflow, run, day, draft=True)


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
        # 仅执行器实现变更时仍复用本日期已完成的同一输入，避免重复融合。
        fence = root / "submissions" / f"{day}.json"
        if fence.is_file():
            prior = json.loads(fence.read_text())
            previous = Path(prior.get("run", str(run))).resolve()
            if previous.is_relative_to((root / "runs").resolve()) and (previous / "run-inputs.json").is_file():
                before = json.loads((previous / "run-inputs.json").read_text())
                current = json.loads((run / "run-inputs.json").read_text())
                for key in ("runner_code", "prepare_code") if prior.get('status') == 'complete' else ('runner_code',):
                    before.pop(key, None); current.pop(key, None)
                if before == current:
                    run = previous
        save_latest(root, {"date": day, "status": "processing", "recordings": len(rows), "blocks": len(chunks), "run": str(run)})
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
                    return {"date": day, "status": "source_retry_pending", "engine": "groq", "run": str(run)}
                trial.cloud("gemini", chunks, root=run)
                gemini_missing = any(not (run / chunk / "gemini-summary.json").is_file() for chunk in chunks)
                if gemini_missing:
                    summary = draft_report(workflow, run, chunks, day)
                trial.sensevoice(config, chunks, root=run)
                if gemini_missing:
                    atomic_bytes(run / "prepare.log", capture.getvalue().encode())
                    return {"date": day, "status": "source_retry_pending", "engine": "gemini", "run": str(run), "summary": summary,
                            "recordings": len(rows), "blocks": len(chunks), "draft": True}
                needed = ("groq-whisper-large-v3-summary.json", "gemini-summary.json", "sensevoice-summary.json")
                if any(not (run / chunk / name).is_file() for chunk in chunks for name in needed):
                    atomic_bytes(run / "prepare.log", capture.getvalue().encode())
                    return {"date": day, "status": "source_retry_pending", "run": str(run)}
                report = trial.prepare_input(root=run, days=chunks)
            atomic_bytes(run / "prepare.log", capture.getvalue().encode())
        final = run / "transcript-v3.md"
        if not report["eligible_for_submission"]:
            draft_summary = draft_report(workflow, run, chunks, day)
            return {"date": day, "status": "source_quality_blocked", "run": str(run), "summary": draft_summary,
                    "recordings": len(rows), "blocks": len(chunks), "draft": True}
        if not final.exists() and report["eligible_for_submission"] and workflow["fusion_mode"] == "auto_validated" and finalize:
            submit_approved(workflow, run, report["input_sha256"], automatic=True, day=day)
        summary = None
        if final.exists():
            # 重建发布副本不触发第二次融合，旧已完成稿也会补齐摘要。
            atomic_bytes(root / "output" / f"{day}.md", final.read_bytes())
            from .summary import summarize
            summary = summarize(workflow, run, day)
        return {"date": day, "status": ("complete" if summary and summary["status"] == "complete" else "summary_failed") if final.exists() else
                (("waiting_finalize" if workflow["fusion_mode"] == "auto_validated" else "waiting_review") if report["eligible_for_submission"] else "source_quality_blocked"),
                "scope": workflow["scope"], "recordings": len(rows), "blocks": len(chunks), "run": str(run),
                "input": str(run / "fusion-input-multiday-v3.md"), "input_sha256": report["input_sha256"],
                "final": str(final) if final.exists() else None, "summary": summary, "waiting_recordings": len(waiting), "sync": synced}
    finally:
        state.close()


FUSED_TIME = r'\d{1,3}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?'
FUSED_PREFIX = r'^\s*(?:[-*]\s+)?(?:\*\*)?\[?(' + FUSED_TIME + r')\]?(?:\*\*)?\s+'


def normalize_fused_response(answer: str) -> str:
    """A missing speaker is explicitly unknown; never infer an identity."""
    return re.sub('(' + FUSED_PREFIX + r')(?!\s*Speaker\b)(.+)$',
                  lambda m: m[1] + 'Speaker ?: ' + m[3], answer, flags=re.M)


def validate_fused_response(answer: str, inventory: list[dict]) -> None:
    if "【他人?】" in answer:
        raise RuntimeError("Output has invalid identity")
    sections = re.split(r"(?=^##\s+录音\s+)", answer, flags=re.M)
    for recording in inventory:
        matching = [s for s in sections if re.match(r"^##\s+录音\s+" + re.escape(recording["id"]) + r"(?:\s|$)", s)]
        if len(matching) != 1:
            raise RuntimeError("Output omitted or duplicated a recording heading")
        # 接受正文的 [MM:SS]、[HH:MM:SS] 或 **HH:MM:SS Speaker ...**，
        # 不把标题中的起始日期时间当成话轮。
        found = re.findall(FUSED_PREFIX + r'Speaker\b', matching[0], re.M)
        if not found:
            raise RuntimeError("Output lacks speaker timestamps")
        times = []
        for value in found:
            try:
                seconds = trial.gemini_seconds(value)
            except ValueError:
                raise RuntimeError("Output has invalid time components")
            times.append(seconds)
        if any(t >= recording["duration_ms"] / 1000 for t in times) or times != sorted(times):
            raise RuntimeError("Output speaker times are out of range or backwards")


def pending_dates(config, workflow, today=None):
    """Detect late arrivals by input identity, even after a day was complete."""
    today = today or datetime.now(ZoneInfo(workflow['timezone'])).date()
    since = (today - timedelta(days=int(workflow.get('backfill_days', 7)))).isoformat()
    root = Path(config['data_root'])
    state = State(root)
    try:
        # Bound new processing to the configured calendar window. Previously
        # queued dates stay eligible across that boundary until complete.
        days = [r[0] for r in state.conn.execute('SELECT DISTINCT local_date FROM recordings WHERE local_date<? ORDER BY local_date', (today.isoformat(),))]
        pending = []
        for day in days:
            rows = [dict(r) for r in state.recordings_for_date(day)]
            path = root / 'status' / f'{day}.json'
            status = json.loads(path.read_text()) if path.exists() else {}
            if status.get('status') == 'outside_backfill_scope' or (day < since and not path.exists()):
                continue
            inventory = []
            if status.get('run'):
                inputs = Path(status['run']) / 'run-inputs.json'
                if inputs.is_file():
                    inventory = json.loads(inputs.read_text()).get('recordings', [])
            current = [{"id":r['recording_id'],"audio":r['sha256'],"duration_ms":r['duration_ms']} for r in sorted(rows,key=lambda r:(r['start_at'],r['recording_id'])) if r['remote_state']=='downloaded']
            if status.get('status')!='complete' or inventory!=current or len(current)!=len(rows):
                pending.append((status.get('checked_at',''), day))
        return [day for _,day in sorted(pending)]
    finally:
        state.close()


def reuse_archive(workflow, config, state):
    archive = Path(config.get('archive_data_root', config['data_root']))
    if archive == Path(config['data_root']) or not (archive / 'state/state.db').is_file():
        return 'not_applicable'
    since = (datetime.now(ZoneInfo(workflow['timezone'])).date() -
             timedelta(days=int(workflow.get('backfill_days', 7)))).isoformat()
    try:
        with sqlite3.connect('file:' + str(archive / 'state/state.db') + '?mode=ro', uri=True) as original:
            original.row_factory = sqlite3.Row
            for row in original.execute("SELECT * FROM recordings WHERE local_date>=? AND remote_state='downloaded'", (since,)):
                previous = state.get_recording(row['recording_id'])
                if previous and previous['remote_state'] == 'downloaded' and previous['sha256'] == row['sha256']:
                    continue
                audio = Path(row['local_path'] or '/nonexistent')
                if audio.is_file() and trial.sha256_file(audio) == row['sha256']:
                    state.upsert_recording(dict(row))
        return 'checked'
    except (sqlite3.Error, OSError):
        # A protected download archive must not stop the runtime account.
        # Use its already-authorized Plaud connection without widening access.
        return 'unavailable_use_upstream'


def run_pending(workflow, config):
    # One complete upstream sync discovers all dates; individual dates then
    # reuse downloaded audio. Failed dates rotate by last attempt, not age.
    state = State(Path(config['data_root']))
    try:
        archive_reuse = reuse_archive(workflow, config, state)
        config = {**config, 'plaud_mcp': {**config['plaud_mcp'], 'lookback_days':
                  max(int(config['plaud_mcp']['lookback_days']), int(workflow.get('backfill_days', 7))+1)}}
        synced = sync_local_dir(config,state) if config['sync_provider']=='local_dir' else asyncio.run(sync_plaud(config,state))
    finally:
        state.close()
    days = pending_dates(config, workflow)
    if not days:
        return {'status':'idle','pending_dates':[], 'sync':synced, 'archive_reuse':archive_reuse}
    for queued in days:
        path = Path(config['data_root']) / 'status' / f'{queued}.json'
        if not path.exists():
            atomic_bytes(path,json.dumps({'date':queued,'status':'queued','checked_at':''}).encode())
    day = days[0]
    result = run_date(workflow,config,day,skip_sync=True,finalize=True)
    return {**result, 'pending_dates':days, 'sync':synced, 'archive_reuse':archive_reuse}


def submit_approved(workflow: dict, run: Path, approved: str, *, automatic: bool = False, day: str | None = None) -> dict:
    if automatic and not day:
        raise RuntimeError('Date required for automatic daily submission')
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
    from .retries import begin, finish, preserve
    if (run / "transcript-v3.md").is_file():
        return {"status": "complete", "final": str(run / "transcript-v3.md"), "input_sha256": approved}
    inventory = json.loads((run / 'run-inputs.json').read_text())['recordings']
    def publish(answer, response_model, usage, elapsed):
        normalized = normalize_fused_response(answer)
        validate_fused_response(normalized, inventory)
        note = '\n缺失说话人标签明确标为 `Speaker ?`，不推断身份；原始融合响应另存。\n' if normalized != answer else ''
        footer = f"\n\n---\n输入 SHA-256：`{approved}`；模型：`{response_model}`；用量：`{json.dumps(usage, ensure_ascii=False)}`；耗时：{elapsed:.1f} 秒。\n" + note
        trial.write_once(run / 'transcript-v3.md', normalized.rstrip() + footer)
    if sentinel.is_file():
        previous = json.loads(sentinel.read_text())
        saved = run / f"response-unvalidated-{previous.get('attempts', 1)}.md"
        if (previous.get('approved_sha256') == approved and previous.get('model') == workflow['fusion_model'] and saved.is_file()):
            try:
                publish(saved.read_text(), previous.get('response_model', workflow['fusion_model']),
                        previous.get('response_usage'), previous.get('elapsed_seconds', 0))
            except RuntimeError:
                pass  # A genuinely invalid saved answer still needs retry.
            else:
                preserve(sentinel, previous)
                finish(sentinel, previous, True, revalidated_saved_response=True)
                if automatic:
                    fence = Path(workflow['data_root'])/'submissions'/f'{day}.json'
                    fence.parent.mkdir(parents=True,exist_ok=True,mode=0o750)
                    trial.write_status(fence, {**previous, 'run':str(run)})
                atomic_bytes(Path(workflow['data_root'])/'output'/f'{day or run.parent.name}.md', (run/'transcript-v3.md').read_bytes())
                return {'status':'complete','final':str(run/'transcript-v3.md'),'input_sha256':approved,'revalidated_saved_response':True}
    status = begin(sentinel, {"approved_sha256": approved, "model": workflow["fusion_model"],
              "approval_kind": "automatic_source_validation" if automatic else "explicit_hash_approval"}, artifact_present=False)
    if status is None:
        return {"status": "fusion_retry_backoff"}
    if automatic:
        if not day:
            raise RuntimeError("Date required for automatic daily submission")
        fence = Path(workflow["data_root"]) / "submissions" / f"{day}.json"
        fence.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        if fence.exists():
            preserve(fence, json.loads(fence.read_text()))
        trial.write_status(fence, {**status, "run": str(run)})
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
        trial.write_once(run / f"response-unvalidated-{status['attempts']}.md", answer.rstrip() + "\n")
        status.update(response_model=result.get('model',workflow['fusion_model']), response_usage=result.get('usage'), elapsed_seconds=round(time.monotonic()-started,2))
        publish(answer, status['response_model'], status['response_usage'], status['elapsed_seconds'])
        finish(sentinel, status, True, usage=result.get("usage"), elapsed_seconds=round(time.monotonic()-started, 2))
    except Exception as error:
        detail = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else str(error).replace(key, "<redacted>")[:300]
        finish(sentinel, status, False, error=detail)
        if automatic:
            trial.write_status(fence, {**status, "run": str(run)})
        raise RuntimeError(f"Fusion failed; automatic backoff scheduled: {detail}") from None
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
    pending = sub.add_parser('run-pending')
    pending.add_argument('--cron', action='store_true', help='Continuously repair pending and late-arriving recording dates')
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
            elif args.command == 'run-pending':
                missing = dependencies(workflow, config)
                result = {'status':'blocked_credentials','missing':missing} if missing else run_pending(workflow, config)
            else:
                day = (args.date or (datetime.now(ZoneInfo(workflow["timezone"])).date() - timedelta(days=1))).isoformat()
                missing = dependencies(workflow, config)
                if args.skip_sync:
                    missing = [m for m in missing if m != "plaud_mcp_login_required"]
                local_now = datetime.now(ZoneInfo(workflow["timezone"]))
                finalize = not args.cron or local_now.hour * 60 + local_now.minute >= 450
                result = {"date": day, "status": "blocked_credentials", "missing": missing} if missing else run_date(workflow, config, day, skip_sync=args.skip_sync, finalize=finalize)
            save_latest(root, result)
            failed = result["status"] in {"blocked_credentials", "source_retry_pending", "source_quality_blocked", "review_input_modified", "daily_submission_already_attempted", "login_failed", "summary_failed"}
            if not getattr(args, "cron", False) or failed:
                print(json.dumps(result, ensure_ascii=False))
            return 2 if failed else 0
    except Exception as error:
        result = {"status": "failed", "error": error.code if isinstance(error, RRException) else type(error).__name__,
                  "detail": str(error)[:300] if isinstance(error, (RuntimeError, RRException, FileExistsError)) else "Inspect local runtime prerequisites"}
        if "day" in locals(): result["date"] = day
        if "root" in locals():
            try:
                save_latest(root, result)
            except OSError:
                pass
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
