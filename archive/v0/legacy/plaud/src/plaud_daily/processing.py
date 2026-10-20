"""Streaming VAD, conservative three-state speaker labels, and local ASR."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from pathlib import Path

import numpy as np
import sherpa_onnx
from opencc import OpenCC

from .audio import ffmpeg_stream, normalize, read_slice
from .core import RRException, State, atomic_jsonl, data_root, hash_json, read_jsonl, sha256_file
from .selection import build_selection


# SenseVoice's language tag can say zh/en while its text contains kana or Hangul.
DISALLOWED_SCRIPT = re.compile(r"[\u3040-\u30ff\uff65-\uff9f\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")


def _model(path: str) -> Path:
    model = Path(path)
    if not model.is_file() or model.stat().st_size == 0:
        raise RRException("model_missing", f"Model missing: {model}")
    return model


def _vad(path: Path, config: dict) -> list[dict]:
    settings = config["vad"]
    model = sherpa_onnx.VadModelConfig()
    model.silero_vad.model = str(_model(settings["model"]))
    model.silero_vad.threshold = float(settings["threshold"])
    model.silero_vad.min_silence_duration = float(settings["min_silence_seconds"])
    model.silero_vad.min_speech_duration = float(settings["min_speech_seconds"])
    model.silero_vad.max_speech_duration = float(settings["max_speech_seconds"])
    model.num_threads = min(3, int(config["audio"]["threads"]))
    vad = sherpa_onnx.VoiceActivityDetector(model, buffer_size_in_seconds=60)
    process = ffmpeg_stream(path)
    segments = []

    def collect():
        while not vad.empty():
            item = vad.front
            samples = np.asarray(item.samples, dtype=np.float32)
            start = int(round(item.start * 1000 / 16000))
            end = start + int(round(len(samples) * 1000 / 16000))
            if end > start:
                segments.append({"start_ms": start, "end_ms": end, "energy": float(np.sqrt(np.mean(samples * samples)))})
            vad.pop()

    try:
        while True:
            data = process.stdout.read(512 * 4)
            if not data:
                break
            if len(data) % 4:
                raise RRException("audio_decode_failed", "FFmpeg returned unaligned PCM")
            vad.accept_waveform(np.frombuffer(data, dtype="<f4"))
            collect()
        vad.flush()
        collect()
        error = process.stderr.read().decode(errors="replace")
        if process.wait() != 0:
            raise RRException("audio_decode_failed", error[:200])
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    return segments


def _speaker_extractor(config: dict):
    path = _model(config["speaker"]["model"])
    settings = sherpa_onnx.SpeakerEmbeddingExtractorConfig()
    settings.model = str(path)
    settings.num_threads = min(3, int(config["audio"]["threads"]))
    return sherpa_onnx.SpeakerEmbeddingExtractor(settings), sha256_file(path)


def _embedding(extractor, samples: np.ndarray) -> np.ndarray:
    stream = extractor.create_stream()
    stream.accept_waveform(16000, samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        raise RRException("speaker_too_short", "Insufficient samples for speaker embedding")
    vector = np.asarray(extractor.compute(stream), dtype=np.float32)
    norm = np.linalg.norm(vector)
    if norm == 0 or not np.isfinite(norm):
        raise RRException("speaker_embedding_invalid", "Invalid speaker embedding")
    return vector / norm


def _templates(root: Path, model_hash: str) -> list[np.ndarray]:
    vectors = []
    for path in sorted((root / "voiceprints/me").glob("*.json")):
        data = json.loads(path.read_text())
        if data.get("model_hash") != model_hash:
            continue
        vector = np.asarray(data["embedding"], dtype=np.float32)
        norm = np.linalg.norm(vector)
        if norm:
            vectors.append(vector / norm)
    return vectors


def _speaker_annotations(root: Path, recording_id: str) -> tuple[dict[str, dict], str | None]:
    path = root / "voiceprints/annotations.jsonl"
    if not path.is_file():
        return {}, None
    rows = {}
    for item in read_jsonl(path):
        if item.get("segment_id", "").startswith(recording_id + ":"):
            if item["segment_id"] in rows:
                raise RRException("speaker_annotation_invalid", "Duplicate speaker annotation")
            if item.get("speaker_label") not in ("me", "other", "uncertain") or type(item.get("contains_me")) is not bool:
                raise RRException("speaker_annotation_invalid", "Invalid speaker annotation")
            rows[item["segment_id"]] = item
    return rows, sha256_file(path)


def preprocess(config: dict, state: State, recording_id: str) -> dict:
    row = state.get_recording(recording_id)
    if not row or row["remote_state"] != "downloaded":
        raise RRException("recording_not_downloaded", "Recording is not downloaded")
    root = data_root(config)
    annotations, annotations_hash = _speaker_annotations(root, recording_id)
    config_hash = hash_json({"audio": config["audio"], "vad": config["vad"], "speaker": config["speaker"], "templates": [(p.name, sha256_file(p)) for p in sorted((root / "voiceprints/me").glob("*.json"))], "annotations_sha256": annotations_hash})
    input_hash = row["sha256"]
    output = root / "work" / recording_id / "segments.jsonl"
    if state.stage_done("recording", recording_id, "preprocess", input_hash, config_hash):
        return {"recording_id": recording_id, "segments": len(read_jsonl(output)), "skipped": True}
    state.begin_stage("recording", recording_id, "preprocess", input_hash, config_hash)
    try:
        audio = normalize(row, root)
        detected = _vad(audio, config)
        extractor, model_hash = _speaker_extractor(config)
        templates = _templates(root, model_hash)
        result = []
        for index, segment in enumerate(detected):
            start, end = segment["start_ms"], segment["end_ms"]
            label, score = "uncertain", None
            if templates and end - start >= int(config["speaker"]["min_embedding_seconds"] * 1000):
                try:
                    vector = _embedding(extractor, read_slice(audio, start, end))
                    score = max(float(np.dot(vector, template)) for template in templates)
                    if score >= float(config["speaker"]["me_threshold"]):
                        label = "me"
                    elif score <= float(config["speaker"]["other_threshold"]):
                        label = "other"
                except RRException:
                    pass
            segment_id = f"{recording_id}:{index:05d}"
            annotation = annotations.get(segment_id)
            if annotation:
                if abs(annotation["start_ms"] - start) > 50 or abs(annotation["end_ms"] - end) > 50:
                    raise RRException("speaker_annotation_stale", f"Annotation boundary changed: {segment_id}")
                label = annotation["speaker_label"]
            result.append({"schema_version": 1, "segment_id": segment_id, "start_ms": start, "end_ms": end, "speaker_label": label, "score": score, "contains_me": annotation["contains_me"] if annotation else label == "me", "speaker_note": annotation.get("note") if annotation else None, "energy": segment["energy"], "discard_candidate": False, "discard_reason": None, "model_id": model_hash, "config_hash": config_hash})
        gap = int(config["speaker"]["neighbor_gap_seconds"] * 1000)
        for index, segment in enumerate(result):
            if segment["speaker_label"] != "uncertain" or segment["end_ms"] - segment["start_ms"] >= int(config["speaker"]["min_embedding_seconds"] * 1000) or index == 0 or index == len(result) - 1:
                continue
            before, after = result[index - 1], result[index + 1]
            if before["speaker_label"] == after["speaker_label"] and before["speaker_label"] in ("me", "other") and 0 <= segment["start_ms"] - before["end_ms"] <= gap and 0 <= after["start_ms"] - segment["end_ms"] <= gap:
                segment["speaker_label"] = before["speaker_label"]
                segment["contains_me"] = before["speaker_label"] == "me"
                segment["inherited"] = True
        atomic_jsonl(output, result)
        state.finish_stage("recording", recording_id, "preprocess", input_hash, config_hash, output, {"segments": len(result), "voice_ms": sum(s["end_ms"] - s["start_ms"] for s in result), "templates": len(templates)})
        return {"recording_id": recording_id, "segments": len(result), "templates": len(templates), "skipped": False}
    except Exception as exc:
        error = exc if isinstance(exc, RRException) else RRException("preprocess_failed", str(exc)[:200])
        state.fail_stage("recording", recording_id, "preprocess", input_hash, config_hash, error)
        raise error from exc


def asr_contract(config: dict, state: State, row) -> tuple[dict, str, str]:
    selection = build_selection(config, state, row)
    model_path = _model(config["asr"]["model"])
    tokens_path = _model(config["asr"]["tokens"])
    config_hash = hash_json({"asr": config["asr"], "model_sha256": sha256_file(model_path), "tokens_sha256": sha256_file(tokens_path), "selection_version": 1, "language_policy_version": 2})
    return selection, selection["input_hash"], config_hash


def transcribe(config: dict, state: State, recording_id: str) -> dict:
    row = state.get_recording(recording_id)
    if not row or row["remote_state"] != "downloaded":
        raise RRException("recording_not_downloaded", "Recording is not downloaded")
    root = data_root(config)
    segments_path = root / "work" / recording_id / "segments.jsonl"
    if not segments_path.is_file():
        raise RRException("preprocess_missing", "Preprocess first")
    selection, input_hash, config_hash = asr_contract(config, state, row)
    selected_ids = {item["segment_id"] for item in selection["segments"] if item["retain_for_asr"]}
    selection_path = root / "work" / recording_id / "selection.jsonl"
    atomic_jsonl(selection_path, selection["segments"])
    output = root / "work" / recording_id / "asr.jsonl"
    checkpoint = root / "work" / recording_id / "asr.partial.jsonl"
    if state.stage_done("recording", recording_id, "asr", input_hash, config_hash):
        return {"recording_id": recording_id, "segments": len(read_jsonl(output)), "selected": selection["retained_count"], "filtered": selection["filtered_count"], "skipped": True}
    if selection["anchor_count"] == 0 and selection["selection_mode"] != "all":
        state.wait_stage("recording", recording_id, "asr", input_hash, config_hash, "no_me_anchor")
        raise RRException("no_me_anchor", "No confident self-speech anchor; audio and selection are preserved for review", 3)
    state.begin_stage("recording", recording_id, "asr", input_hash, config_hash)
    try:
        model_path = Path(config["asr"]["model"])
        model_hash = sha256_file(model_path)
        result = []
        if checkpoint.is_file():
            candidate = read_jsonl(checkpoint)
            if all(item.get("input_hash") == input_hash and item.get("config_hash") == config_hash for item in candidate):
                result = candidate
        completed = {item["segment_id"] for item in result}
        since_checkpoint = 0
        recognizer = None
        converter = None
        audio = None
        if selected_ids:
            recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(model=str(model_path), tokens=config["asr"]["tokens"], num_threads=min(3, int(config["audio"]["threads"])), language=config["asr"]["language"], use_itn=bool(config["asr"]["use_itn"]))
            converter = OpenCC("t2s")
            audio = normalize(row, root)
        for segment in read_jsonl(segments_path):
            if segment["segment_id"] not in selected_ids:
                continue
            start, end = segment["start_ms"], segment["end_ms"]
            width = min(60000, int(config["asr"]["max_chunk_seconds"] * 1000))
            expected_ids = [segment["segment_id"] + (f":{part}" if end - start > width else "") for part, _ in enumerate(range(start, end, width))]
            if all(item in completed for item in expected_ids):
                continue
            result = [item for item in result if item["segment_id"] not in expected_ids]
            for part, offset in enumerate(range(start, end, width)):
                finish = min(end, offset + width)
                samples = read_slice(audio, offset, finish)
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, samples)
                recognizer.decode_stream(stream)
                recognition = stream.result
                raw = recognition.text.strip()
                normalized = converter.convert(raw)
                language_match = re.fullmatch(r"<\|([a-z]+)\|>", getattr(recognition, "lang", ""))
                language = language_match.group(1) if language_match else "unknown"
                tagged_language_allowed = language in config["asr"]["allowed_languages"]
                disallowed_script = bool(DISALLOWED_SCRIPT.search(normalized))
                allowed = tagged_language_allowed and not disallowed_script
                reason = None if allowed else ("language_not_allowed" if not tagged_language_allowed else "script_not_allowed")
                result.append({"schema_version": 2, "segment_id": segment["segment_id"] + (f":{part}" if end - start > width else ""), "start_ms": offset, "end_ms": finish, "speaker_label": segment["speaker_label"], "speaker_note": segment.get("speaker_note"), "raw_text": raw, "text": normalized, "language": language, "language_allowed": allowed, "filter_reason": reason, "event": getattr(recognition, "event", None), "suspected_hallucination": not raw or bool(re.fullmatch(r"[\W_]+", raw)), "model_id": model_hash, "input_hash": input_hash, "config_hash": config_hash})
            completed.update(expected_ids)
            since_checkpoint += 1
            if since_checkpoint >= 100:
                atomic_jsonl(checkpoint, result)
                since_checkpoint = 0
        atomic_jsonl(checkpoint, result)
        atomic_jsonl(output, result)
        metrics = {"segments": len(result), "selected": selection["retained_count"], "filtered_by_context": selection["filtered_count"], "filtered_by_language": sum(not item["language_allowed"] for item in result), "selection_sha256": sha256_file(selection_path)}
        state.finish_stage("recording", recording_id, "asr", input_hash, config_hash, output, metrics)
        return {"recording_id": recording_id, **metrics, "skipped": False}
    except Exception as exc:
        error = exc if isinstance(exc, RRException) else RRException("asr_failed", str(exc)[:200])
        state.fail_stage("recording", recording_id, "asr", input_hash, config_hash, error)
        raise error from exc


def enroll(config: dict, source: Path) -> dict:
    if not source.is_file():
        raise RRException("enroll_input_missing", "Enrollment audio not found")
    # Enrollment is explicit; a short or multi-speaker recording cannot silently become "me".
    detected = _vad(source, config)
    speech_ms = sum(item["end_ms"] - item["start_ms"] for item in detected)
    if speech_ms < 30000 or len(detected) == 0:
        raise RRException("enroll_insufficient_speech", "Need at least 30 seconds of clean self speech")
    extractor, model_hash = _speaker_extractor(config)
    embeddings = []
    eligible_ms = 0
    for item in detected:
        duration_ms = item["end_ms"] - item["start_ms"]
        # Very short VAD islands make CAM++ embeddings unstable; keep them for
        # transcription but do not let them veto an otherwise clean enrollment.
        if duration_ms >= 3000:
            embeddings.append(_embedding(extractor, read_slice(source, item["start_ms"], item["end_ms"])))
            eligible_ms += duration_ms
    if len(embeddings) < 3 or eligible_ms < 30000:
        raise RRException("enroll_insufficient_speech", "Need at least three stable segments and 30 seconds of eligible speech")
    center = np.mean(embeddings, axis=0)
    center /= np.linalg.norm(center)
    similarity = [float(np.dot(center, item)) for item in embeddings]
    if len(similarity) > 1 and min(similarity) < 0.72:
        raise RRException("enroll_possible_multiple_speakers", "Sample has inconsistent voices")
    root = data_root(config)
    output = root / "voiceprints/me" / (sha256_file(source)[:24] + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    from .core import atomic_bytes, now_iso
    atomic_bytes(output, (json.dumps({"schema_version": 1, "model_hash": model_hash, "source_hash": sha256_file(source), "created_at": now_iso(), "embedding": center.tolist(), "speech_ms": speech_ms, "eligible_ms": eligible_ms, "segment_count": len(embeddings), "min_similarity": min(similarity)}, ensure_ascii=False) + "\n").encode())
    return {"template": str(output), "speech_ms": speech_ms, "eligible_ms": eligible_ms, "segment_count": len(embeddings), "min_similarity": min(similarity)}
