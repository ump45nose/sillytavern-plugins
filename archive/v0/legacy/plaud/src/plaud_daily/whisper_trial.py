"""Independent no-VAD faster-whisper comparison; does not touch production output."""

from __future__ import annotations

import argparse
import hashlib
import json
import resource
import time
from pathlib import Path

from faster_whisper import WhisperModel


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    audio_hash = sha256_file(args.audio)
    started = time.monotonic()
    model = WhisperModel(str(args.model_dir), device="cpu", compute_type="int8",
                         cpu_threads=3, num_workers=1)
    segments, info = model.transcribe(str(args.audio), language="zh", beam_size=5,
                                      vad_filter=False, condition_on_previous_text=True)
    rows = [{"start_seconds": round(segment.start, 3), "end_seconds": round(segment.end, 3),
             "text": segment.text.strip()} for segment in segments]
    if not rows or max(row["end_seconds"] for row in rows) < 1100:
        raise RuntimeError("Whisper did not produce coverage near the end of the 20-minute excerpt")
    jsonl = args.output / "whisper-small.jsonl"
    jsonl.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    lines = ["# faster-whisper small / CPU int8 / 无 VAD", "",
             "> 同一 20 分钟连续音频；未做 VAD；时间段由 Whisper 自身解码器输出，非人物标签。", ""]
    lines += [f"- {int(row['start_seconds']) // 60:02d}:{int(row['start_seconds']) % 60:02d} {row['text']}" for row in rows]
    (args.output / "whisper-small.md").write_text("\n".join(lines) + "\n")
    metrics = {"audio_sha256": audio_hash, "engine": "faster-whisper", "model": "small",
               "model_sha256": sha256_file(args.model_dir / "model.bin"),
               "compute_type": "int8", "language": "zh", "vad": False,
               "detected_language_probability": info.language_probability,
               "segments": len(rows), "elapsed_seconds": round(time.monotonic() - started, 2),
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    (args.output / "whisper-small-summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(metrics, ensure_ascii=False))


if __name__ == "__main__":
    main()
