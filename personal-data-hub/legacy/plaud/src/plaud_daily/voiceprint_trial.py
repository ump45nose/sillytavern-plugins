"""Offline, non-destructive meeting-domain voiceprint trial.

The six enrollment segments below were explicitly confirmed as pure self speech.
Trial results are separate from production segments.jsonl and never drive ASR.
"""

from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np

from .audio import normalize, read_slice
from .core import State, atomic_jsonl, data_root, load_config, read_jsonl, sha256_file
from .processing import _embedding, _speaker_extractor


SOURCE_ID = "of_dfd11c9e7a7b15f3e15da0c9a45b298b"
ENROLLMENT_INDICES = (21, 23, 24, 55, 56, 58)
TEST_IDS = (SOURCE_ID, "of_ad0721cee3c4c3014796142ca7a0f063")
WINDOW_MS = 3000
STRIDE_MS = 1000


def _score(vector: np.ndarray, templates: list[np.ndarray]) -> float:
    return max(float(np.dot(vector, template)) for template in templates)


def _windows(samples: np.ndarray, extractor, templates: list[np.ndarray], start_ms: int) -> list[dict]:
    width = WINDOW_MS * 16
    if len(samples) < width:
        return []
    last = len(samples) - width
    starts = list(range(0, last + 1, STRIDE_MS * 16))
    if starts[-1] != last:
        starts.append(last)
    result = []
    for offset in starts:
        vector = _embedding(extractor, samples[offset:offset + width])
        result.append({"start_ms": start_ms + round(offset / 16), "end_ms": start_ms + round((offset + width) / 16), "score": round(_score(vector, templates), 6)})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    args = parser.parse_args()
    config = load_config(args.config)
    root = data_root(config)
    state = State(root)
    started = time.monotonic()
    try:
        extractor, model_hash = _speaker_extractor(config)
        source = state.get_recording(SOURCE_ID)
        source_audio = normalize(source, root)
        source_rows = read_jsonl(root / "work" / SOURCE_ID / "segments.jsonl")
        enrollment = []
        for index in ENROLLMENT_INDICES:
            segment = source_rows[index]
            enrollment.append(_embedding(extractor, read_slice(source_audio, segment["start_ms"], segment["end_ms"])))
        center = np.mean(enrollment, axis=0)
        center /= np.linalg.norm(center)
        candidate = root / "voiceprints/candidates/meeting-2026-09-24-cam.json"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        from .core import atomic_bytes
        atomic_bytes(candidate, (json.dumps({
            "schema_version": 1, "status": "trial_only", "model_hash": model_hash,
            "source_recording_id": SOURCE_ID, "source_sha256": source["sha256"],
            "enrollment_segment_ids": [source_rows[i]["segment_id"] for i in ENROLLMENT_INDICES],
            "embedding": center.tolist(),
        }, ensure_ascii=False) + "\n").encode())
        summary = {"candidate": str(candidate), "model_hash": model_hash, "recordings": []}
        for recording_id in TEST_IDS:
            row = state.get_recording(recording_id)
            audio = normalize(row, root)
            segments = read_jsonl(root / "work" / recording_id / "segments.jsonl")
            output = []
            counts = {"total": len(segments), "scoreable": 0, "old_me": 0, "meeting_me": 0, "either_me": 0, "mixed_candidate": 0}
            for segment in segments:
                start, end = segment["start_ms"], segment["end_ms"]
                item = {
                    "segment_id": segment["segment_id"], "start_ms": start, "end_ms": end,
                    "old_label": segment["speaker_label"], "old_score": segment["score"],
                    "enrollment": recording_id == SOURCE_ID and int(segment["segment_id"].rsplit(":", 1)[1]) in ENROLLMENT_INDICES,
                    "meeting_score": None, "meeting_label": "uncertain", "window_max": None,
                    "self_windows": [], "mixed_candidate": False,
                }
                if end - start >= int(config["speaker"]["min_embedding_seconds"] * 1000):
                    samples = read_slice(audio, start, end)
                    try:
                        vector = _embedding(extractor, samples)
                        score = _score(vector, [center])
                        item["meeting_score"] = round(score, 6)
                        item["meeting_label"] = "me" if score >= config["speaker"]["me_threshold"] else "other" if score <= config["speaker"]["other_threshold"] else "uncertain"
                        counts["scoreable"] += 1
                        if item["meeting_label"] == "me":
                            counts["meeting_me"] += 1
                        if segment["speaker_label"] == "me":
                            counts["old_me"] += 1
                        if item["meeting_label"] == "me" or segment["speaker_label"] == "me":
                            counts["either_me"] += 1
                        if end - start >= WINDOW_MS and item["meeting_label"] != "me":
                            windows = _windows(samples, extractor, [center], start)
                            item["window_max"] = max(window["score"] for window in windows)
                            item["self_windows"] = [window for window in windows if window["score"] >= 0.65]
                            item["mixed_candidate"] = item["window_max"] >= 0.70
                            if item["mixed_candidate"]:
                                counts["mixed_candidate"] += 1
                    except Exception as exc:
                        item["error"] = str(exc)[:160]
                output.append(item)
            path = root / "work" / recording_id / "voiceprint-trial-meeting-2026-09-24.jsonl"
            atomic_jsonl(path, output)
            counts.update({"recording_id": recording_id, "path": str(path), "sha256": sha256_file(path)})
            summary["recordings"].append(counts)
            print(json.dumps(counts, ensure_ascii=False), flush=True)
        summary["elapsed_seconds"] = round(time.monotonic() - started, 2)
        summary["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        state.close()


if __name__ == "__main__":
    main()
