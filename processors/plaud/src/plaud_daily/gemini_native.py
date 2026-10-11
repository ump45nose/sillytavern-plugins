"""使用既有 CPA 的 Gemini 原生音频格式，并保留上游过滤诊断。"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .core import atomic_bytes
from .multiday_trial import inspect_gemini

PROMPT = (
    "Generate a verbatim transcript of the speech in this audio. "
    "The speech is Chinese; preserve English terms. "
    "Include relative timestamps and anonymous speakers on each line using this format: "
    "[mm:ss] Speaker 1: text. Mark unclear words as [听不清] and overlapping speech as [重叠]. "
)


def normalize_timestamp_brackets(content: str) -> str:
    """补齐模型遗漏的时间戳方括号；不改时间、文字或说话人。"""
    return re.sub(r"^(\s*(?:[-*]\s*)?)(\d{1,2}:\d{2}(?::\d{2})?)(\s+Speaker\s+[\d?]+\s*[:：]\s*.+)$",
                  r"\1[\2]\3", content, flags=re.M)


def publish_response(audio: bytes, output: Path, model: str, wire: dict, seconds: float, elapsed: float) -> dict:
    """拒绝空候选、截断和异常时间；保留可定位的上游诊断。"""
    candidates = wire.get("candidates", [])
    diagnostic = {"model": model, "transport": "gemini_native", "audio_sha256": hashlib.sha256(audio).hexdigest(),
                  "elapsed_seconds": round(elapsed, 2), "candidate_count": len(candidates),
                  "prompt_feedback": wire.get("promptFeedback"), "usage": wire.get("usageMetadata"),
                  "model_version": wire.get("modelVersion"),
                  "finish_reasons": [c.get("finishReason") for c in candidates]}
    atomic_bytes(output / "gemini-response-diagnostic.json", json.dumps(diagnostic, ensure_ascii=False, indent=2).encode())
    if not candidates:
        feedback = wire.get("promptFeedback", {})
        raise RuntimeError("Gemini no candidate; block_reason=" + str(feedback.get("blockReason", "unknown")) +
                           "; inspect gemini-response-diagnostic.json")
    candidate = candidates[0]
    raw = "\n".join(p["text"] for p in candidate.get("content", {}).get("parts", []) if p.get("text") and not p.get("thought"))
    if candidate.get("finishReason") != "STOP" or not raw.strip():
        raise RuntimeError("Gemini native response incomplete; finish=" + str(candidate.get("finishReason")))
    atomic_bytes(output / "gemini-raw-transcript.md", (raw.strip() + "\n").encode())
    content = normalize_timestamp_brackets(raw)
    timing = inspect_gemini(content, seconds)
    diagnostic["timing"] = timing
    atomic_bytes(output / "gemini-response-diagnostic.json", json.dumps(diagnostic, ensure_ascii=False, indent=2).encode())
    if not timing["valid"]:
        raise RuntimeError("Gemini timestamps invalid; inspect gemini-raw-transcript.md")
    atomic_bytes(output / "gemini-transcript.md", ("# Gemini 原生音频转录（未经人工校对）\n\n" + content.strip() + "\n").encode())
    summary = {**diagnostic, "finish_reason": "stop", "timestamp_brackets_normalized": content != raw}
    atomic_bytes(output / "gemini-summary.json", json.dumps(summary, ensure_ascii=False, indent=2).encode())
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    key = os.environ["CPA_PUBLIC_API_KEY"]
    audio = args.audio.read_bytes()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(args.audio)], capture_output=True, text=True, check=True)
    seconds = float(probe.stdout.strip())
    prompt = PROMPT + f"The audio lasts {seconds:.2f} seconds; timestamps start at 00:00 and stay below {int(seconds) // 60:02d}:{int(seconds) % 60:02d}."
    base = args.url.removesuffix("/v1/chat/completions").rstrip("/")
    url = base + "/v1beta/models/" + urllib.parse.quote(args.model, safe="") + ":generateContent"
    body = {"contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "audio/mpeg", "data": base64.b64encode(audio).decode()}}, {"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 16000}}
    request = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            wire = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Gemini native route HTTP {error.code}") from None
    summary = publish_response(audio, args.output, args.model, wire, seconds, time.monotonic() - started)
    print(json.dumps({k: summary[k] for k in ("audio_sha256", "model", "transport", "finish_reason", "elapsed_seconds")}))


if __name__ == "__main__":
    main()
