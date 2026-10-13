"""Offline, no-VAD ASR comparison on one fixed continuous audio excerpt.

This is an experiment only: it never modifies production ASR or daily output.
"""

from __future__ import annotations

import argparse
import json
import re
import resource
import subprocess
import time
from pathlib import Path

import numpy as np
import sherpa_onnx
from opencc import OpenCC

from .core import atomic_bytes, atomic_jsonl, load_config, sha256_file


def plaud_excerpt(source: Path, offset_seconds: int, duration_seconds: int) -> list[dict]:
    contents = source.read_text(encoding="utf-8")
    headers = list(re.finditer(r"(?m)^(\d{2}):(\d{2}):(\d{2}) Speaker (\d+)\s*$", contents))
    rows = []
    for index, match in enumerate(headers):
        absolute = int(match[1]) * 3600 + int(match[2]) * 60 + int(match[3])
        if not offset_seconds <= absolute < offset_seconds + duration_seconds:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(contents)
        rows.append({"offset_seconds": absolute - offset_seconds, "speaker": int(match[4]),
                     "text": contents[match.end():end].strip()})
    return rows


def run(args: argparse.Namespace) -> None:
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    audio_hash = sha256_file(args.audio)
    config = load_config(args.config)
    model = Path(config["asr"]["model"])
    tokens = Path(config["asr"]["tokens"])
    contract = {"audio_sha256": audio_hash, "model_sha256": sha256_file(model),
                "tokens_sha256": sha256_file(tokens), "language": "zh", "vad": False,
                "window_seconds": args.window_seconds, "duration_seconds": args.duration_seconds,
                "offset_seconds": args.offset_seconds, "source": str(args.source)}
    manifest = output / "manifest.json"
    if manifest.is_file() and json.loads(manifest.read_text())["contract"] != contract:
        raise RuntimeError("Existing experiment contract differs; choose a fresh output directory")
    plaud = plaud_excerpt(args.source, args.offset_seconds, args.duration_seconds)
    atomic_jsonl(output / "plaud.jsonl", plaud)
    plaud_lines = ["# Plaud 同期片段（未经人工金标核验）", ""]
    plaud_lines += [f"- {r['offset_seconds'] // 60:02d}:{r['offset_seconds'] % 60:02d} Speaker {r['speaker']} {r['text']}" for r in plaud]
    atomic_bytes(output / "plaud.md", ("\n".join(plaud_lines) + "\n").encode())

    start = time.monotonic()
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=min(3, int(config["audio"]["threads"])),
        language="zh", use_itn=bool(config["asr"]["use_itn"]))
    decoder = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(args.audio),
                                "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], stdout=subprocess.PIPE)
    assert decoder.stdout is not None
    converter = OpenCC("t2s")
    rows = []
    samples_per_window = args.window_seconds * 16000
    for index in range((args.duration_seconds + args.window_seconds - 1) // args.window_seconds):
        raw = decoder.stdout.read(samples_per_window * 4)
        if not raw:
            break
        samples = np.frombuffer(raw, dtype="<f4")
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        recognizer.decode_stream(stream)
        rows.append({"start_seconds": index * args.window_seconds,
                     "end_seconds": index * args.window_seconds + len(samples) / 16000,
                     "raw_text": stream.result.text.strip(),
                     "text": converter.convert(stream.result.text.strip())})
    decoder.stdout.close()
    exit_code = decoder.wait()
    if exit_code != 0 or len(rows) != (args.duration_seconds + args.window_seconds - 1) // args.window_seconds:
        raise RuntimeError(f"Incomplete audio decode: exit={exit_code}, windows={len(rows)}")
    atomic_jsonl(output / "sensevoice-fixed.jsonl", rows)
    lines = ["# SenseVoice int8 / 固定 25 秒窗口 / 无 VAD", "",
             "> 整段音频连续读取，每一秒都送入模型；固定窗口只满足 SenseVoice 短音频输入限制。无人物身份输出。", ""]
    lines += [f"- {r['start_seconds'] // 60:02d}:{r['start_seconds'] % 60:02d} {r['text'] or '（空）'}" for r in rows]
    atomic_bytes(output / "sensevoice-fixed.md", ("\n".join(lines) + "\n").encode())
    metrics = {"contract": contract, "plaud_utterances": len(plaud), "windows": len(rows),
               "elapsed_seconds": round(time.monotonic() - start, 2),
               "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    atomic_bytes(manifest, (json.dumps(metrics, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"output": str(output), **metrics}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config")
    parser.add_argument("--offset-seconds", type=int, default=6260)
    parser.add_argument("--duration-seconds", type=int, default=1200)
    parser.add_argument("--window-seconds", type=int, default=25)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
