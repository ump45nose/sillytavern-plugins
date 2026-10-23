"""Transcribe versioned diarization speech units without touching daily output."""

from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import sherpa_onnx
from opencc import OpenCC

from .audio import read_slice
from .core import RRException, atomic_bytes, atomic_jsonl, load_config, read_jsonl, sha256_file


def _write_preview(experiment: Path, rows: list[dict]) -> None:
    preview = ["# 试验转写（未经人工验收）", "", "> 说话人标签来自未校准聚类；重叠语音未分离成干净单人音轨。此稿不用于正式每日输出。", ""]
    for item in sorted(rows, key=lambda row: (row["start_ms"], row["unit_id"])):
        at = f"{item['start_ms'] // 60000:02d}:{item['start_ms'] % 60000 // 1000:02d}"
        label = "【重叠】" if item["overlap"] else "【候选我】" if item["speaker_candidate"] == "me" else "【未确定】"
        preview.append(f"- {at} {label} {item['text'].replace(chr(10), ' ') or '（无可识别文本）'}")
    atomic_bytes(experiment / "preview.md", ("\n".join(preview) + "\n").encode())


def run(config: dict, experiment: Path) -> dict:
    summary_path = experiment / "summary.json"
    units_path = experiment / "asr_units.jsonl"
    if not summary_path.is_file() or not units_path.is_file():
        raise RRException("trial_missing", "Run the diarization trial first")
    summary = json.loads(summary_path.read_text())
    if summary.get("status") != "experimental_unvalidated":
        raise RRException("trial_invalid", "Unexpected diarization experiment")
    if experiment.parent.name == "trial":
        audio = experiment.parent.parent / "audio.wav"
    elif experiment.parent.name == "experiments":
        audio = Path(summary["audio_path"]) if "audio_path" in summary else None
    else:
        raise RRException("trial_invalid", "Unknown experiment location")
    if audio is None or not audio.is_file() or sha256_file(audio) != summary["contract"]["audio_sha256"]:
        raise RRException("trial_audio_changed", "Experiment audio is missing or changed")
    model = Path(config["asr"]["model"])
    tokens = Path(config["asr"]["tokens"])
    if not model.is_file() or not tokens.is_file():
        raise RRException("trial_asr_model_missing", "SenseVoice model or tokens missing")
    contract = {"units_sha256": sha256_file(units_path), "audio_sha256": sha256_file(audio),
                "model_sha256": sha256_file(model), "tokens_sha256": sha256_file(tokens),
                "language": "zh", "engine": "sensevoice", "version": 1}
    output = experiment / "asr-sensevoice.jsonl"
    marker = experiment / "asr-sensevoice-summary.json"
    if marker.is_file():
        old = json.loads(marker.read_text())
        if old.get("contract") == contract and output.is_file() and old.get("output_sha256") == sha256_file(output):
            if not (experiment / "preview.md").is_file():
                _write_preview(experiment, read_jsonl(output))
            return {"path": str(output), "skipped": True, **old["metrics"]}
        raise RRException("trial_output_conflict", str(output))
    checkpoint = experiment / "asr-sensevoice.partial.jsonl"
    saved = read_jsonl(checkpoint) if checkpoint.is_file() else []
    if any(item.get("contract") != contract for item in saved):
        saved = []
    completed = {item["unit_id"] for item in saved}
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=min(3, int(config["audio"]["threads"])),
        language="zh", use_itn=bool(config["asr"]["use_itn"]))
    converter = OpenCC("t2s")
    started = time.monotonic()
    since_checkpoint = 0
    for unit in read_jsonl(units_path):
        if unit["unit_id"] in completed:
            continue
        if unit["end_ms"] - unit["start_ms"] > 25_000:
            raise RRException("trial_asr_unit_invalid", "Speech unit exceeds 25 seconds")
        samples = read_slice(audio, unit["start_ms"], unit["end_ms"])
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        saved.append({"unit_id": unit["unit_id"], "start_ms": unit["start_ms"], "end_ms": unit["end_ms"],
                      "speaker_candidate": unit["speaker_candidate"], "cluster_id": unit["cluster_id"],
                      "overlap": unit["overlap"], "raw_text": result.text.strip(),
                      "text": converter.convert(result.text.strip()), "language_tag": getattr(result, "lang", ""),
                      "contract": contract})
        completed.add(unit["unit_id"])
        since_checkpoint += 1
        if since_checkpoint >= 50:
            atomic_jsonl(checkpoint, saved)
            since_checkpoint = 0
    atomic_jsonl(checkpoint, saved)
    atomic_jsonl(output, saved)
    _write_preview(experiment, saved)
    metrics = {"units": len(saved), "elapsed_seconds": round(time.monotonic() - started, 2),
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
               "speaker_labels_validated": False, "cer_validated": False}
    atomic_bytes(marker, (json.dumps({"contract": contract, "output_sha256": sha256_file(output), "metrics": metrics}, ensure_ascii=False, indent=2) + "\n").encode())
    return {"path": str(output), "skipped": False, **metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--experiment", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(load_config(args.config), args.experiment), ensure_ascii=False))


if __name__ == "__main__":
    main()
