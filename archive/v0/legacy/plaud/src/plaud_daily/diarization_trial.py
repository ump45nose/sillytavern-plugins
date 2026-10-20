"""Versioned, offline diarization trial; never writes production speaker labels."""

from __future__ import annotations

import argparse
import json
import math
import resource
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import sherpa_onnx

from .audio import ffmpeg_stream, normalize, read_slice
from .core import RRException, State, atomic_bytes, atomic_jsonl, data_root, hash_json, load_config, read_jsonl, sha256_file
from .gold import SCENES
from .processing import _embedding


BLOCK_MS = 1_200_000
OVERLAP_MS = 5_000
MAX_UNIT_MS = 25_000
MIN_EMBED_MS = 1_500
MODEL_NAME = "sherpa-onnx-pyannote-segmentation-3-0/model.int8.onnx"
ENROLLMENT_NAME = "self-2026-09-26-five-clips.json"


def _decode(path: Path, start_ms: int, end_ms: int) -> np.ndarray:
    if end_ms <= start_ms or end_ms - start_ms > BLOCK_MS + 2 * OVERLAP_MS:
        raise RRException("trial_audio_window_invalid", "Diarization block is out of bounds")
    process = ffmpeg_stream(path, start_ms=start_ms, duration_ms=end_ms - start_ms)
    data, error = process.communicate()
    if process.returncode or len(data) % 4:
        raise RRException("trial_audio_decode_failed", error.decode(errors="replace")[:200])
    return np.frombuffer(data, dtype="<f4").copy()


def _extractor(path: Path, threads: int):
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig()
    config.model = str(path)
    config.num_threads = threads
    return sherpa_onnx.SpeakerEmbeddingExtractor(config)


def _template(root: Path, config: dict, model_path: Path, extractor) -> tuple[np.ndarray, str]:
    enrolled = json.loads((root / "voiceprints/me" / ENROLLMENT_NAME).read_text())
    if enrolled.get("source_recording_id") != "of_0b2bb36d9181ddc260119e402bce1a42" or len(enrolled.get("enrollment_boundaries_ms", [])) != 5:
        raise RRException("trial_template_invalid", "Expected five user-confirmed 9/26 enrollment clips")
    model_hash = sha256_file(model_path)
    if enrolled["model_hash"] == model_hash:
        vector = np.asarray(enrolled["embedding"], dtype=np.float32)
        return vector / np.linalg.norm(vector), sha256_file(root / "voiceprints/me" / ENROLLMENT_NAME)
    state = State(root)
    try:
        row = state.get_recording(enrolled["source_recording_id"])
        if not row or row["sha256"] != enrolled["source_sha256"]:
            raise RRException("trial_template_invalid", "Original enrollment audio changed")
        audio = normalize(row, root)
        vectors = [_embedding(extractor, read_slice(audio, start, end)) for start, end in enrolled["enrollment_boundaries_ms"]]
    finally:
        state.close()
    center = np.mean(vectors, axis=0)
    center /= np.linalg.norm(center)
    return center, hash_json({"enrollment_sha256": sha256_file(root / "voiceprints/me" / ENROLLMENT_NAME), "model_sha256": model_hash})


def _mark_overlap(turns: list[dict]) -> None:
    ordered = sorted(turns, key=lambda item: (item["start_ms"], item["end_ms"]))
    for index, item in enumerate(ordered):
        for other in ordered[index + 1:]:
            if other["start_ms"] >= item["end_ms"]:
                break
            if other["cluster_id"] != item["cluster_id"]:
                item["overlap"] = True
                other["overlap"] = True


def _cluster_scores(turns: list[dict], samples: np.ndarray, decode_start_ms: int, extractor, template: np.ndarray) -> list[dict]:
    groups = defaultdict(list)
    for item in turns:
        groups[item["cluster_id"]].append(item)
    result = []
    for cluster_id, parts in sorted(groups.items()):
        vectors = []
        weights = []
        for item in parts:
            if item["overlap"] or item["end_ms"] - item["start_ms"] < MIN_EMBED_MS:
                continue
            left = max(0, round((item["start_ms"] - decode_start_ms) * 16))
            right = min(len(samples), round((item["end_ms"] - decode_start_ms) * 16))
            if right - left < MIN_EMBED_MS * 16:
                continue
            if right - left > 20_000 * 16:
                middle = (left + right) // 2
                left, right = middle - 10_000 * 16, middle + 10_000 * 16
            try:
                vectors.append(_embedding(extractor, samples[left:right]))
                weights.append(min((right - left) / 16_000, 10.0))
            except RRException:
                continue
        score = None
        kept = 0
        if len(vectors) >= 2 and sum(weights) >= 8:
            matrix = np.stack(vectors)
            preliminary = np.average(matrix, axis=0, weights=weights)
            preliminary /= np.linalg.norm(preliminary)
            order = np.argsort(matrix @ preliminary)[::-1]
            selected = order[:max(2, math.ceil(len(order) * 0.8))]
            center = np.average(matrix[selected], axis=0, weights=np.asarray(weights)[selected])
            center /= np.linalg.norm(center)
            score = float(center @ template)
            kept = len(selected)
        result.append({"cluster_id": cluster_id, "turns": len(parts), "embedding_candidates": len(vectors),
                       "embedding_kept": kept, "clean_speech_ms": sum(item["end_ms"] - item["start_ms"] for item in parts if not item["overlap"]),
                       "self_score": round(score, 6) if score is not None else None})
    return result


def _units(turns: list[dict]) -> list[dict]:
    ordered = sorted(turns, key=lambda item: (item["start_ms"], item["end_ms"], item["turn_id"]))
    units = []
    current = None
    for item in ordered:
        for start in range(item["start_ms"], item["end_ms"], MAX_UNIT_MS):
            part = {**item, "start_ms": start, "end_ms": min(item["end_ms"], start + MAX_UNIT_MS)}
            gap = part["start_ms"] - current["end_ms"] if current else None
            compatible = current and not part["overlap"] and not current["overlap"] and part["cluster_id"] == current["cluster_id"] and part["chunk_id"] == current["chunk_id"] and 0 <= gap < 1000 and part["end_ms"] - current["start_ms"] <= MAX_UNIT_MS
            if compatible:
                compatible = not any(other["cluster_id"] != part["cluster_id"] and other["start_ms"] < part["start_ms"] and other["end_ms"] > current["end_ms"] for other in ordered)
            if compatible:
                current["end_ms"] = part["end_ms"]
                current["source_turn_ids"].append(part["turn_id"])
            else:
                current = {"unit_id": f"unit-{len(units):05d}", "start_ms": part["start_ms"], "end_ms": part["end_ms"],
                           "chunk_id": part["chunk_id"], "cluster_id": part["cluster_id"], "speaker_candidate": part["speaker_candidate"],
                           "overlap": part["overlap"], "source_turn_ids": [part["turn_id"]]}
                units.append(current)
    return units


def run(config: dict, scene: str | None, recording_id: str | None, cluster_threshold: float, identity_threshold: float, embedding_kind: str = "cam") -> dict:
    root = data_root(config)
    segmentation = root / "models/experimental" / MODEL_NAME
    embedding = Path(config["speaker"]["model"]) if embedding_kind == "cam" else root / "models/experimental/eres2net-base-zh.onnx"
    for model in (segmentation, embedding):
        if not model.is_file():
            raise RRException("trial_model_missing", str(model))
    if scene:
        folder = root / "gold/v1" / scene
        manifest = json.loads((folder / "manifest.json").read_text())
        audio = folder / "audio.wav"
        if sha256_file(audio) != manifest["wav_sha256"]:
            raise RRException("gold_audio_changed", scene)
        duration_ms = manifest["duration_ms"]
        source_offset = manifest["start_ms"]
        target_base = folder / "trial"
    else:
        state = State(root)
        try:
            row = state.get_recording(recording_id)
            if not row or row["remote_state"] != "downloaded":
                raise RRException("recording_not_downloaded", str(recording_id))
            audio = normalize(row, root)
            duration_ms = row["duration_ms"]
            source_offset = 0
        finally:
            state.close()
        target_base = root / "work" / recording_id / "experiments"
    threads = min(3, int(config["audio"]["threads"]))
    extractor = _extractor(embedding, threads)
    template, template_hash = _template(root, config, embedding, extractor)
    contract = {"audio_sha256": sha256_file(audio), "segmentation_sha256": sha256_file(segmentation),
                "embedding_sha256": sha256_file(embedding), "template_sha256": template_hash,
                "block_ms": BLOCK_MS, "overlap_ms": OVERLAP_MS, "cluster_threshold": cluster_threshold,
                "identity_threshold": identity_threshold, "min_duration_on": 0.2, "min_duration_off": 0.2, "version": 1}
    if embedding_kind != "cam":
        contract["embedding_kind"] = embedding_kind
    experiment_id = f"diarization-{embedding_kind}-" + hash_json(contract)[:12]
    target = target_base / experiment_id
    summary_path = target / "summary.json"
    if summary_path.is_file():
        old = json.loads(summary_path.read_text())
        if old.get("contract") == contract and all((target / name).is_file() for name in ("turns.jsonl", "clusters.jsonl", "asr_units.jsonl")):
            return {"experiment": str(target), "skipped": True, **old["metrics"]}
        raise RRException("trial_output_conflict", str(target))
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(segmentation)), num_threads=threads),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(embedding), num_threads=threads),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=-1, threshold=cluster_threshold),
        min_duration_on=0.2, min_duration_off=0.2)
    model = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    started = time.monotonic()
    all_turns = []
    all_clusters = []
    for core_start in range(0, duration_ms, BLOCK_MS):
        core_end = min(duration_ms, core_start + BLOCK_MS)
        decode_start = max(0, core_start - OVERLAP_MS)
        decode_end = min(duration_ms, core_end + OVERLAP_MS)
        samples = _decode(audio, decode_start, decode_end)
        diarized = model.process(samples)
        chunk_id = f"chunk-{core_start // BLOCK_MS:04d}"
        turns = []
        for segment in diarized.sort_by_start_time():
            left = max(core_start, decode_start + round(segment.start * 1000))
            right = min(core_end, decode_start + round(segment.end * 1000))
            if right <= left:
                continue
            turns.append({"turn_id": f"turn-{len(all_turns) + len(turns):05d}", "chunk_id": chunk_id,
                          "cluster_id": f"{chunk_id}:{segment.speaker}", "start_ms": left, "end_ms": right,
                          "overlap": False, "diarization_confidence": round(float(segment.confidence), 6) if math.isfinite(segment.confidence) else None})
        _mark_overlap(turns)
        clusters = _cluster_scores(turns, samples, decode_start, extractor, template)
        lookup = {item["cluster_id"]: item for item in clusters}
        for item in turns:
            score = lookup[item["cluster_id"]]["self_score"]
            item["self_score"] = score
            item["speaker_candidate"] = "overlap" if item["overlap"] else "me" if score is not None and score >= identity_threshold else "uncertain"
            item["source_start_ms"] = source_offset + item["start_ms"]
            item["source_end_ms"] = source_offset + item["end_ms"]
        all_turns.extend(turns)
        all_clusters.extend(clusters)
        del samples
    units = _units(all_turns)
    metrics = {"turns": len(all_turns), "clusters": len(all_clusters), "asr_units": len(units),
               "candidate_me_turns": sum(item["speaker_candidate"] == "me" for item in all_turns),
               "overlap_turns": sum(item["overlap"] for item in all_turns),
               "elapsed_seconds": round(time.monotonic() - started, 2),
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "identity_calibrated": False}
    atomic_jsonl(target / "turns.jsonl", all_turns)
    atomic_jsonl(target / "clusters.jsonl", all_clusters)
    atomic_jsonl(target / "asr_units.jsonl", units)
    atomic_bytes(summary_path, (json.dumps({"status": "experimental_unvalidated", "audio_path": str(audio), "contract": contract, "metrics": metrics}, ensure_ascii=False, indent=2) + "\n").encode())
    return {"experiment": str(target), "skipped": False, **metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scene", choices=[item[0] for item in SCENES])
    group.add_argument("--recording-id")
    parser.add_argument("--cluster-threshold", type=float, default=0.5)
    parser.add_argument("--identity-threshold", type=float, help="Uncalibrated candidate threshold; required for ERes2NetV2")
    parser.add_argument("--embedding", choices=("cam", "eres2net"), default="cam")
    args = parser.parse_args()
    if args.embedding == "eres2net" and args.identity_threshold is None:
        parser.error("ERes2NetV2 needs a separately calibrated --identity-threshold")
    identity_threshold = args.identity_threshold if args.identity_threshold is not None else 0.65
    if not 0 < args.cluster_threshold < 1 or not 0 < identity_threshold < 1:
        raise RRException("trial_threshold_invalid", "Thresholds must be between 0 and 1")
    print(json.dumps(run(load_config(args.config), args.scene, args.recording_id, args.cluster_threshold, identity_threshold, args.embedding), ensure_ascii=False))


if __name__ == "__main__":
    main()
