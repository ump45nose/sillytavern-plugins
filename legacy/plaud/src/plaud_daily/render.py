"""Date-scoped transcript publication."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .core import RRException, State, atomic_bytes, data_root, hash_json, read_jsonl, sha256_file
from .processing import asr_contract
from .sync import parse_utc


LABELS = {"me": "【我】", "other": "【他人】", "uncertain": "【未确定】"}


def render_recording(config: dict, state: State, recording_id: str) -> dict:
    """Publish a clearly scoped test transcript without claiming a complete day."""
    row = state.get_recording(recording_id)
    if not row or row["remote_state"] != "downloaded":
        raise RRException("recording_not_downloaded", "Recording is not downloaded")
    root = data_root(config)
    segments_path = root / "work" / recording_id / "segments.jsonl"
    asr_path = root / "work" / recording_id / "asr.jsonl"
    if not segments_path.is_file() or not asr_path.is_file():
        raise RRException("asr_missing", "Recording ASR is incomplete")
    asr_hash = sha256_file(asr_path)
    selection, asr_input, asr_config = asr_contract(config, state, row)
    valid = state.conn.execute("SELECT 1 FROM stage_runs WHERE scope_type='recording' AND scope_id=? AND stage='asr' AND status='done' AND input_hash=? AND config_hash=? AND artifact_hash=? LIMIT 1", (recording_id, asr_input, asr_config, asr_hash)).fetchone()
    if not valid:
        raise RRException("asr_incomplete", "ASR artifact does not match current segments")
    input_hash = hash_json({"recording_id": recording_id, "asr_sha256": asr_hash})
    config_hash = hash_json({"timezone": config["timezone"], "labels": LABELS, "context": config["context"], "allowed_languages": config["asr"]["allowed_languages"], "format": "single-recording-v3"})
    output = root / "work" / recording_id / "transcript.md"
    if state.stage_done("recording", recording_id, "render_recording", input_hash, config_hash):
        return {"recording_id": recording_id, "output": str(output), "skipped": True}
    state.begin_stage("recording", recording_id, "render_recording", input_hash, config_hash)
    try:
        origin = parse_utc(row["start_at"])
        zone = ZoneInfo(config["timezone"])
        audited = read_jsonl(asr_path)
        items = [item for item in audited if item["language_allowed"]]
        durations = {key: 0 for key in LABELS}
        lines = [f"# 单条录音测试稿 · {row['local_date']}", "", "> 仅覆盖这一条录音，不是当日完整转写稿。说话人标签是模型预测，未经人工标注验收。", "", f"录音 ID：`{recording_id}` · 时长：{row['duration_ms'] / 3600000:.2f} 小时 · 原语音片段：{len(selection['segments'])} · 已选语音片段：{selection['retained_count']} · 发布：{len(items)}", ""]
        lines.append(f"模式：{'全录音语音段' if selection['selection_mode'] == 'all' else '本人发言上下文'} · 未选取 {selection['filtered_count']} 段 · 语言/文字过滤 {len(audited) - len(items)} 段；原音频与审计清单保留。")
        lines.append("")
        for item in items:
            label = item["speaker_label"]
            if label not in LABELS:
                raise RRException("asr_contract_changed", "Unknown speaker label")
            durations[label] += item["end_ms"] - item["start_ms"]
        total = sum(durations.values())
        lines.append("说话时长：" + " · ".join(f"{LABELS[key]} {value / 60000:.1f} 分钟 ({value / total:.1%})" if total else f"{LABELS[key]} 0 分钟" for key, value in durations.items()))
        lines.append("")
        for item in sorted(items, key=lambda x: (x["start_ms"], x["segment_id"])):
            at = (origin + timedelta(milliseconds=item["start_ms"])).astimezone(zone).strftime("%Y-%m-%d %H:%M:%S")
            speech = item["text"].replace("\n", " ").strip() or "（无可识别文本）"
            mark = " [疑似空白/噪声]" if item["suspected_hallucination"] else ""
            if item.get("speaker_note"):
                mark += f" [说话人：{item['speaker_note']}]"
            lines.append(f"- {at} {LABELS[item['speaker_label']]} {speech}{mark}")
        atomic_bytes(output, ("\n".join(lines) + "\n").encode())
        state.finish_stage("recording", recording_id, "render_recording", input_hash, config_hash, output, {"segments": len(items), "speaker_ms": durations, "filtered_by_context": selection["filtered_count"], "filtered_by_language": len(audited) - len(items)})
        return {"recording_id": recording_id, "output": str(output), "segments": len(items), "speaker_ms": durations, "filtered_by_context": selection["filtered_count"], "filtered_by_language": len(audited) - len(items), "skipped": False}
    except Exception as exc:
        error = exc if isinstance(exc, RRException) else RRException("render_failed", str(exc)[:200])
        state.fail_stage("recording", recording_id, "render_recording", input_hash, config_hash, error)
        raise error from exc


def render(config: dict, state: State, date: str) -> dict:
    rows = state.recordings_for_date(date)
    if not rows:
        raise RRException("output_incomplete", "No recordings for date")
    root = data_root(config)
    inputs = []
    missing = []
    for row in rows:
        path = root / "work" / row["recording_id"] / "asr.jsonl"
        segments_path = root / "work" / row["recording_id"] / "segments.jsonl"
        if row["remote_state"] != "downloaded" or not path.is_file() or not segments_path.is_file():
            missing.append(row["recording_id"])
        else:
            selection, current_input, current_config = asr_contract(config, state, row)
            digest = sha256_file(path)
            valid = state.conn.execute("SELECT 1 FROM stage_runs WHERE scope_type='recording' AND scope_id=? AND stage='asr' AND status='done' AND input_hash=? AND config_hash=? AND artifact_hash=? LIMIT 1", (row["recording_id"], current_input, current_config, digest)).fetchone()
            if valid:
                inputs.append((row, path, digest, selection))
            else:
                missing.append(row["recording_id"])
    if missing:
        raise RRException("output_incomplete", f"{len(missing)} recordings waiting or missing ASR", 3)
    input_hash = hash_json({"date": date, "asr": [(row["recording_id"], digest) for row, _, digest, _ in inputs]})
    config_hash = hash_json({"timezone": config["timezone"], "labels": LABELS, "context": config["context"], "allowed_languages": config["asr"]["allowed_languages"], "format": 2})
    output = root / "output" / f"{date}.md"
    if state.stage_done("date", date, "render", input_hash, config_hash):
        return {"date": date, "output": str(output), "recordings": len(rows), "skipped": True}
    state.begin_stage("date", date, "render", input_hash, config_hash)
    try:
        segments = []
        durations = {key: 0 for key in LABELS}
        filtered_context = filtered_language = 0
        for row, path, _, selection in inputs:
            origin = parse_utc(row["start_at"])
            filtered_context += selection["filtered_count"]
            for segment in read_jsonl(path):
                if not segment["language_allowed"]:
                    filtered_language += 1
                    continue
                label = segment["speaker_label"]
                if label not in LABELS:
                    raise RRException("asr_contract_changed", "Unknown speaker label")
                at = origin + timedelta(milliseconds=segment["start_ms"])
                durations[label] += segment["end_ms"] - segment["start_ms"]
                segments.append((at, row["recording_id"], segment))
        segments.sort(key=lambda item: (item[0], item[1], item[2]["segment_id"]))
        total = sum(durations.values())
        lines = [f"# {date} 录音转写", "", f"录音：{len(rows)} 条 · 语音：{total / 60000:.1f} 分钟 · 片段：{len(segments)} 条", "", f"过滤：不在【我】前后 {config['context']['me_window_minutes']} 分钟的 {filtered_context} 段 · 语言/文字 {filtered_language} 段。原始音频及审计清单保留。", "", "说话时长：" + " · ".join(f"{LABELS[key]} {value / 60000:.1f} 分钟 ({value / total:.1%})" if total else f"{LABELS[key]} 0 分钟" for key, value in durations.items()), "", "> 自动转写可能有误；【未确定】不代表他人。原始音频保留用于核对。", ""]
        local_zone = ZoneInfo(config["timezone"])
        for at, recording_id, segment in segments:
            local_at = at.astimezone(local_zone)
            timestamp = local_at.strftime("%H:%M:%S" if local_at.date().isoformat() == date else "%Y-%m-%d %H:%M:%S")
            text = segment["text"].replace("\n", " ").strip()
            if not text:
                text = "（无可识别文本）"
            note = " [疑似空白/噪声]" if segment["suspected_hallucination"] else ""
            if segment.get("speaker_note"):
                note += f" [说话人：{segment['speaker_note']}]"
            lines.append(f"- {timestamp} {LABELS[segment['speaker_label']]} {text}{note} · `{recording_id[-8:]}`")
        atomic_bytes(output, ("\n".join(lines) + "\n").encode())
        state.finish_stage("date", date, "render", input_hash, config_hash, output, {"recordings": len(rows), "segments": len(segments), "speaker_ms": durations, "filtered_by_context": filtered_context, "filtered_by_language": filtered_language})
        return {"date": date, "output": str(output), "recordings": len(rows), "segments": len(segments), "speaker_ms": durations, "filtered_by_context": filtered_context, "filtered_by_language": filtered_language, "skipped": False}
    except Exception as exc:
        error = exc if isinstance(exc, RRException) else RRException("render_failed", str(exc)[:200])
        state.fail_stage("date", date, "render", input_hash, config_hash, error)
        raise error from exc
