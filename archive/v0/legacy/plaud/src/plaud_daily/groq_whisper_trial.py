"""Blind, no-VAD Groq Whisper large-v3 trial on a fixed continuous audio file.

The Groq API key is read only from GROQ_API_KEY. This experiment never changes
production transcriptions, voiceprints, or pipeline state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"


def _field(boundary: str, name: str, value: str) -> bytes:
    return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n"
            f"\r\n{value}\r\n").encode()


def _time(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 60:02d}:{whole % 60:02d}"


def run(audio: Path, output: Path) -> dict:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set; never paste it into command arguments")
    contents = audio.read_bytes()
    if not contents or len(contents) > 25_000_000:
        raise RuntimeError("Audio is empty or exceeds the documented 25 MB free-tier limit")
    digest = hashlib.sha256(contents).hexdigest()
    boundary = f"plaud-{uuid.uuid4().hex}"
    fields = {
        "model": MODEL,
        "language": "zh",
        "response_format": "verbose_json",
        "timestamp_granularities[]": "segment",
        "temperature": "0",
    }
    body = b"".join(_field(boundary, name, value) for name, value in fields.items())
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{audio.name}\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode()
    body += contents + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": "curl/8.5.0"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        # Report only selected diagnostic fields; never print the request or credential.
        detail = ""
        try:
            parsed = json.loads(error.read(2048))
            problem = parsed.get("error", parsed)
            if isinstance(problem, dict):
                detail = str(problem.get("message") or problem.get("code") or problem.get("type") or "")
        except (ValueError, UnicodeDecodeError):
            pass
        detail = re.sub(r"gsk_[A-Za-z0-9]+", "<redacted>", detail.replace(key, "<redacted>"))[:300]
        server = error.headers.get("Server", "unknown")
        raise RuntimeError(f"Groq transcription HTTP {error.code}; server={server}; detail={detail or 'unavailable'}") from None
    if not isinstance(result.get("text"), str) or not result["text"].strip():
        raise RuntimeError("Groq returned no transcription text")
    segments = result.get("segments") or []
    if not isinstance(segments, list):
        raise RuntimeError("Groq returned invalid segments")
    lines = ["# Groq Whisper large-v3 / 连续 20 分钟 / 无 VAD", "",
             "> 同一 MP3 文件一次提交；语言固定 `zh`；未提供 Plaud 稿或热词；Whisper 不输出人物身份。", ""]
    if segments:
        lines.extend(f"- {_time(float(item['start']))} {item.get('text', '').strip()}"
                     for item in segments)
    else:
        lines.append(result["text"].strip())
    summary = {
        "audio_sha256": digest,
        "audio_bytes": len(contents),
        "model": MODEL,
        "language": "zh",
        "vad": False,
        "client_chunking": False,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "segments": len(segments),
        "first_segment_seconds": float(segments[0]["start"]) if segments else None,
        "last_segment_seconds": float(segments[-1]["end"]) if segments else None,
        "text_chars": len(result["text"]),
        "endpoint": ENDPOINT,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "groq-whisper-large-v3.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    (output / "groq-whisper-large-v3.md").write_text("\n".join(lines) + "\n")
    (output / "groq-whisper-large-v3-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.audio, args.output)


if __name__ == "__main__":
    main()
