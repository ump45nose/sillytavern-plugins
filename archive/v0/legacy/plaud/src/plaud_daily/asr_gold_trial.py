"""Gold-aligned SenseVoice A/B: old VAD fragments versus merged speaker turns."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
import unicodedata
from pathlib import Path

import sherpa_onnx
from opencc import OpenCC

from .audio import read_slice
from .core import RRException, atomic_bytes, atomic_jsonl, data_root, load_config, read_jsonl, sha256_file
from .evaluate_trial import _annotations
from .gold import SCENES


def _plain(text: str, converter: OpenCC) -> str:
    normalized = unicodedata.normalize("NFKC", converter.convert(text)).casefold()
    return "".join(char for char in normalized if not unicodedata.category(char).startswith(("P", "Z", "C")))


def _edits(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for column, other in enumerate(right, 1):
            current.append(min(previous[column] + 1, current[-1] + 1, previous[column - 1] + (char != other)))
        previous = current
    return previous[-1]


def _gold_units(rows: list[dict]) -> list[dict]:
    ordered = sorted((item for item in rows if item["gold_speaker"] in ("me", "other") and item["exclude"].strip() != "1"),
                     key=lambda item: (item["start_ms"], item["end_ms"]))
    result = []
    for item in ordered:
        if any(other is not item and other["exclude"].strip() != "1" and other["start_ms"] < item["end_ms"] and other["end_ms"] > item["start_ms"] for other in rows):
            continue  # overlapped speech is reported separately, not scored as single-speaker ASR
        if item["end_ms"] - item["start_ms"] > 25_000:
            raise RRException("gold_turn_too_long", "Split gold turns longer than 25 seconds")
        previous = result[-1] if result else None
        gap = item["start_ms"] - previous["end_ms"] if previous else None
        can_merge = previous and previous["speaker"] == item["gold_speaker"] and 0 <= gap < 1000 and item["end_ms"] - previous["start_ms"] <= 25_000
        if can_merge:
            can_merge = not any(other["exclude"].strip() != "1" and other["gold_speaker"] != item["gold_speaker"] and other["start_ms"] < item["start_ms"] and other["end_ms"] > previous["end_ms"] for other in rows)
        if can_merge:
            previous["end_ms"] = item["end_ms"]
            previous["reference_text"] += item["gold_text"]
        else:
            result.append({"unit_id": f"gold-{len(result):04d}", "start_ms": item["start_ms"], "end_ms": item["end_ms"],
                           "speaker": item["gold_speaker"], "reference_text": item["gold_text"]})
    return result


def _fragments(rows: list[dict], offset: int, unit: dict) -> list[tuple[int, int]]:
    fragments = []
    for item in rows:
        left = max(unit["start_ms"], item["start_ms"] - offset)
        right = min(unit["end_ms"], item["end_ms"] - offset)
        if right - left >= 300:
            fragments.append((left, right))
    return fragments


def run(config: dict, scene: str, mode: str) -> dict:
    root = data_root(config)
    folder = root / "gold/v1" / scene
    rows, manifest = _annotations(folder)
    audio = folder / "audio.wav"
    if sha256_file(audio) != manifest["wav_sha256"]:
        raise RRException("gold_audio_changed", scene)
    units = _gold_units(rows)
    if not units:
        raise RRException("gold_no_speech", scene)
    model = Path(config["asr"]["model"])
    tokens = Path(config["asr"]["tokens"])
    contract = {"gold_sha256": sha256_file(folder / "annotations.tsv"), "audio_sha256": manifest["wav_sha256"],
                "model_sha256": sha256_file(model), "tokens_sha256": sha256_file(tokens), "mode": mode,
                "language": "zh", "use_itn": bool(config["asr"]["use_itn"]), "version": 1}
    output = folder / f"asr-gold-{mode}.jsonl"
    summary_path = folder / f"asr-gold-{mode}-summary.json"
    if summary_path.is_file():
        old = json.loads(summary_path.read_text())
        if old.get("contract") == contract and output.is_file() and old.get("output_sha256") == sha256_file(output):
            return {"path": str(output), "skipped": True, **old["metrics"]}
        raise RRException("trial_output_conflict", str(output))
    checkpoint = folder / f"asr-gold-{mode}.partial.jsonl"
    saved = read_jsonl(checkpoint) if checkpoint.is_file() else []
    if any(item.get("contract") != contract for item in saved):
        saved = []
    done = {item["unit_id"] for item in saved}
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=min(3, int(config["audio"]["threads"])),
        language="zh", use_itn=bool(config["asr"]["use_itn"]))
    converter = OpenCC("t2s")
    vad_rows = read_jsonl(root / "work" / manifest["recording_id"] / "segments.jsonl") if mode == "fragmented" else []
    started = time.monotonic()
    since_checkpoint = 0
    for unit in units:
        if unit["unit_id"] in done:
            continue
        ranges = [(unit["start_ms"], unit["end_ms"])] if mode == "merged" else _fragments(vad_rows, manifest["start_ms"], unit)
        parts = []
        for left, right in ranges:
            stream = recognizer.create_stream()
            stream.accept_waveform(16000, read_slice(audio, left, right))
            recognizer.decode_stream(stream)
            parts.append(converter.convert(stream.result.text.strip()))
        text = "".join(parts)
        reference = _plain(unit["reference_text"], converter)
        hypothesis = _plain(text, converter)
        saved.append({**unit, "recognized_text": text, "fragment_count": len(ranges),
                      "reference_characters": len(reference), "character_edits": _edits(reference, hypothesis), "contract": contract})
        done.add(unit["unit_id"])
        since_checkpoint += 1
        if since_checkpoint >= 50:
            atomic_jsonl(checkpoint, saved)
            since_checkpoint = 0
    atomic_jsonl(checkpoint, saved)
    atomic_jsonl(output, saved)
    per_speaker = {}
    for speaker in ("me", "other"):
        subset = [item for item in saved if item["speaker"] == speaker]
        chars = sum(item["reference_characters"] for item in subset)
        edits = sum(item["character_edits"] for item in subset)
        per_speaker[speaker] = {"units": len(subset), "reference_characters": chars, "character_edits": edits,
                                "cer": round(edits / chars, 6) if chars else None}
    metrics = {"units": len(saved), "speaker_cer": per_speaker,
               "elapsed_seconds": round(time.monotonic() - started, 2),
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "method": "same-human-gold-turns-fragmented-vs-merged", "overlap_excluded": True}
    atomic_bytes(summary_path, (json.dumps({"contract": contract, "output_sha256": sha256_file(output), "metrics": metrics}, ensure_ascii=False, indent=2) + "\n").encode())
    return {"path": str(output), "skipped": False, **metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--scene", choices=[item[0] for item in SCENES], required=True)
    parser.add_argument("--mode", choices=("fragmented", "merged"), required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(run(load_config(args.config), args.scene, args.mode), ensure_ascii=False))
    except RRException as error:
        print(json.dumps({"ok": False, "error_code": error.code, "error": str(error)}, ensure_ascii=False))
        sys.exit(3 if error.code == "gold_not_finalized" else error.exit_code)


if __name__ == "__main__":
    main()
