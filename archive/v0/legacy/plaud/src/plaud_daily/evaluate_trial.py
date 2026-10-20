"""Human-gold-gated, duration-weighted speaker evaluation for offline trials."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .core import RRException, atomic_bytes, data_root, load_config, read_jsonl, sha256_file
from .gold import DURATION_MS, SCENES


def _annotations(folder: Path) -> tuple[list[dict], dict]:
    manifest = json.loads((folder / "manifest.json").read_text())
    path = folder / "annotations.tsv"
    marker = folder / "human-reviewed.json"
    if not marker.is_file() or json.loads(marker.read_text()).get("annotations_sha256") != sha256_file(path):
        raise RRException("gold_not_finalized", "Human review must cover the full audio and be finalized")
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows or any(not item["gold_speaker"].strip() and item["exclude"].strip() != "1" for item in rows):
        raise RRException("gold_incomplete", "Every candidate row must be reviewed, split, deleted or excluded")
    for item in rows:
        item["start_ms"] = int(item["start_ms"])
        item["end_ms"] = int(item["end_ms"])
    return rows, manifest


def _score(rows: list[dict], excluded: list[list[int]], turns: list[dict]) -> dict:
    boundaries = {0, DURATION_MS}
    for item in rows + turns:
        boundaries.update((item["start_ms"], item["end_ms"]))
    for left, right in excluded:
        boundaries.update((left, right))
    points = sorted(point for point in boundaries if 0 <= point <= DURATION_MS)
    tp = fp = fn = overlap_ms = overlap_hit_ms = uncertain_ms = 0
    for left, right in zip(points, points[1:]):
        if left == right or any(left < end and right > start for start, end in excluded):
            continue
        active_gold = {item["gold_speaker"] for item in rows if item["start_ms"] < right and item["end_ms"] > left and item["exclude"].strip() != "1"}
        if "unintelligible" in active_gold:
            continue
        predicted = {item["speaker_candidate"] for item in turns if item["start_ms"] < right and item["end_ms"] > left}
        duration = right - left
        if "overlap" in active_gold or ("me" in active_gold and "other" in active_gold):
            overlap_ms += duration
            if "overlap" in predicted:
                overlap_hit_ms += duration
            continue
        truth_me = "me" in active_gold
        predicted_me = "me" in predicted
        if truth_me and predicted_me:
            tp += duration
        elif truth_me:
            fn += duration
        elif predicted_me:
            fp += duration
        if "uncertain" in predicted:
            uncertain_ms += duration
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tp_ms": tp, "fp_ms": fp, "fn_ms": fn, "me_precision": round(precision, 6),
            "me_recall": round(recall, 6), "me_f1": round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0,
            "gold_overlap_ms": overlap_ms, "overlap_detected_ms": overlap_hit_ms, "predicted_uncertain_ms": uncertain_ms}


def run(config: dict, scene: str, experiment: Path) -> dict:
    root = data_root(config)
    folder = root / "gold/v1" / scene
    if experiment.parent != folder / "trial":
        raise RRException("trial_scene_mismatch", "Experiment does not belong to this gold scene")
    rows, manifest = _annotations(folder)
    turns_path = experiment / "turns.jsonl"
    turns = read_jsonl(turns_path)
    excluded = list(manifest["excluded_enrollment_intervals_ms"])
    excluded.extend([item["start_ms"], item["end_ms"]] for item in rows if item["exclude"].strip() == "1")
    metrics = _score(rows, excluded, turns)
    report = {"scene": scene, "experiment": str(experiment), "annotations_sha256": sha256_file(folder / "annotations.tsv"),
              "turns_sha256": sha256_file(turns_path), "metrics": metrics, "identity_threshold_calibrated": False,
              "note": "This scores one uncalibrated trial. Enrollment overlap and gold overlaps are excluded from the primary me metric."}
    output = experiment / "speaker-evaluation.json"
    atomic_bytes(output, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--scene", choices=[item[0] for item in SCENES], required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(load_config(args.config), args.scene, args.experiment), ensure_ascii=False))
    except RRException as error:
        print(json.dumps({"ok": False, "error_code": error.code, "error": str(error)}, ensure_ascii=False))
        sys.exit(3 if error.code == "gold_not_finalized" else error.exit_code)


if __name__ == "__main__":
    main()
