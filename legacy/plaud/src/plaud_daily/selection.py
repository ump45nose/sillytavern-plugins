"""Auditable speech selection around confidently recognized self speech."""

from __future__ import annotations

from bisect import bisect_right
from pathlib import Path

from .core import RRException, State, data_root, hash_json, read_jsonl, sha256_file
from .sync import parse_utc


def _origin_ms(row) -> int:
    return round(parse_utc(row["start_at"]).timestamp() * 1000)


def _merged_windows(anchors: list[tuple[int, int]], margin_ms: int) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted((a - margin_ms, b + margin_ms) for a, b in anchors):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def build_selection(config: dict, state: State, row) -> dict:
    """Use all currently known, preprocessed recordings assigned to this local day."""
    root = data_root(config)
    sources = []
    anchors: list[tuple[int, int]] = []
    current = None
    for peer in state.recordings_for_date(row["local_date"]):
        path = root / "work" / peer["recording_id"] / "segments.jsonl"
        if peer["remote_state"] != "downloaded" or not path.is_file():
            raise RRException("context_incomplete", "All known recordings for the date need preprocessing before ASR", 3)
        source_hash = sha256_file(path)
        if not state.conn.execute("SELECT 1 FROM stage_runs WHERE scope_type='recording' AND scope_id=? AND stage='preprocess' AND status='done' AND input_hash=? AND artifact_hash=? LIMIT 1", (peer["recording_id"], peer["sha256"], source_hash)).fetchone():
            raise RRException("context_incomplete", "A recording's speaker artifact is not current", 3)
        parts = read_jsonl(path)
        origin = _origin_ms(peer)
        sources.append((peer["recording_id"], peer["start_at"], source_hash))
        anchors.extend((origin + part["start_ms"], origin + part["end_ms"]) for part in parts if part.get("contains_me", part["speaker_label"] == "me"))
        if peer["recording_id"] == row["recording_id"]:
            current = parts
    if current is None:
        raise RRException("recording_missing", "Recording is not part of its assigned date")
    full_recording = config["context"].get("selection_mode") == "all"
    margin_ms = int(config["context"]["me_window_minutes"]) * 60000
    windows = [] if full_recording else _merged_windows(anchors, margin_ms)
    starts = [window[0] for window in windows]
    origin = _origin_ms(row)
    selected = []
    retained_ms = 0
    for part in current:
        left, right = origin + part["start_ms"], origin + part["end_ms"]
        index = bisect_right(starts, right) - 1
        keep = full_recording or (index >= 0 and windows[index][1] >= left)
        if keep:
            retained_ms += part["end_ms"] - part["start_ms"]
        selected.append({"segment_id": part["segment_id"], "start_ms": part["start_ms"], "end_ms": part["end_ms"], "speaker_label": part["speaker_label"], "retain_for_asr": keep, "reason": "full_recording" if full_recording else ("me_context" if keep else ("no_me_anchor" if not anchors else "outside_me_window"))})
    input_hash = hash_json({"raw": row["sha256"], "sources": sources, "context": config["context"], "selection": [(item["segment_id"], item["retain_for_asr"]) for item in selected]})
    return {"segments": selected, "anchor_count": len(anchors), "retained_count": sum(item["retain_for_asr"] for item in selected), "filtered_count": sum(not item["retain_for_asr"] for item in selected), "retained_ms": retained_ms, "input_hash": input_hash, "source_hashes": sources, "window_count": len(windows), "selection_mode": "all" if full_recording else "me_context"}
