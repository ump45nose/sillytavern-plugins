"""Build and retest a voiceprint from explicitly user-confirmed pure-self segments."""

from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np

from .audio import normalize, read_slice
from .core import RRException, State, atomic_bytes, atomic_jsonl, data_root, load_config, read_jsonl, sha256_file
from .processing import _embedding, _speaker_extractor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--indices", required=True, help="Comma-separated, user-confirmed pure-self VAD indices")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    indices = [int(item) for item in args.indices.split(",")]
    if len(indices) < 3 or len(indices) != len(set(indices)) or not args.name.replace("-", "").isalnum():
        raise RRException("enrollment_invalid", "Need at least three distinct indices and a safe name")
    config = load_config(args.config)
    root = data_root(config)
    state = State(root)
    started = time.monotonic()
    try:
        row = state.get_recording(args.recording_id)
        if not row or row["remote_state"] != "downloaded":
            raise RRException("recording_not_downloaded", "Enrollment recording is unavailable")
        segments = read_jsonl(root / "work" / args.recording_id / "segments.jsonl")
        chosen = [segments[index] for index in indices]
        if any(item["segment_id"] != f"{args.recording_id}:{index:05d}" for index, item in zip(indices, chosen)):
            raise RRException("enrollment_invalid", "Segment index does not match recording")
        durations = [item["end_ms"] - item["start_ms"] for item in chosen]
        if min(durations) < 3000 or sum(durations) < 30000:
            raise RRException("enrollment_insufficient_speech", "Need at least 30 seconds total and 3 seconds per segment")
        audio = normalize(row, root)
        extractor, model_hash = _speaker_extractor(config)
        embeddings = [_embedding(extractor, read_slice(audio, item["start_ms"], item["end_ms"])) for item in chosen]
        center = np.mean(embeddings, axis=0)
        center /= np.linalg.norm(center)
        leave_one_out = []
        for index, vector in enumerate(embeddings):
            others = np.mean([item for other_index, item in enumerate(embeddings) if other_index != index], axis=0)
            others /= np.linalg.norm(others)
            leave_one_out.append(round(float(np.dot(vector, others)), 6))
        candidate = root / "voiceprints/candidates" / (args.name + ".json")
        atomic_bytes(candidate, (json.dumps({
            "schema_version": 1, "status": "user_confirmed", "model_hash": model_hash,
            "source_recording_id": args.recording_id, "source_sha256": row["sha256"],
            "enrollment_segment_ids": [item["segment_id"] for item in chosen],
            "enrollment_boundaries_ms": [[item["start_ms"], item["end_ms"]] for item in chosen],
            "eligible_ms": sum(durations), "leave_one_out_scores": leave_one_out,
            "embedding": center.tolist(),
        }, ensure_ascii=False) + "\n").encode())
        result = []
        transitions = {}
        for segment in segments:
            start, end = segment["start_ms"], segment["end_ms"]
            score = None
            label = "uncertain"
            if end - start >= int(config["speaker"]["min_embedding_seconds"] * 1000):
                vector = _embedding(extractor, read_slice(audio, start, end))
                score = float(np.dot(vector, center))
                label = "me" if score >= config["speaker"]["me_threshold"] else "other" if score <= config["speaker"]["other_threshold"] else "uncertain"
            key = segment["speaker_label"] + "->" + label
            transitions[key] = transitions.get(key, 0) + 1
            result.append({
                "segment_id": segment["segment_id"], "start_ms": start, "end_ms": end,
                "prior_label": segment["speaker_label"], "new_label": label,
                "new_score": round(score, 6) if score is not None else None,
                "enrollment": segment["segment_id"] in {item["segment_id"] for item in chosen},
            })
        path = root / "work" / args.recording_id / ("voiceprint-retest-" + args.name + ".jsonl")
        atomic_jsonl(path, result)
        print(json.dumps({
            "candidate": str(candidate), "candidate_sha256": sha256_file(candidate),
            "retest": str(path), "retest_sha256": sha256_file(path),
            "enrollment_segments": len(chosen), "enrollment_seconds": round(sum(durations) / 1000, 2),
            "leave_one_out_scores": leave_one_out, "transitions": transitions,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }, ensure_ascii=False))
    finally:
        state.close()


if __name__ == "__main__":
    main()
