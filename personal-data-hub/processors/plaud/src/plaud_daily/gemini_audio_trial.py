"""Experimental one-shot Gemini audio transcription through an existing CPA route.

No production files are touched. API key must be supplied via environment.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


PROMPT = """识别目标语言固定为中文（zh），英文专名和术语保留原语。请逐字转写这段连续录音，不要摘要、润色、补全听不清的内容，也不要参考任何既有转写稿。
只输出带相对时间戳的逐句文本，格式：[mm:ss] Speaker 1: 原话。说话人编号在整段内保持一致；无法可靠区分则写 Speaker ?。
英语术语保留原语；听不清写[听不清]，多人重叠写[重叠]。不要编造音频里没有的话。"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3-flash")
    parser.add_argument("--url", default="http://192.168.31.201:8317/v1/chat/completions")
    args = parser.parse_args()
    key = os.environ.get("CPA_PUBLIC_API_KEY")
    if not key:
        raise RuntimeError("CPA_PUBLIC_API_KEY is not set")
    contents = args.audio.read_bytes()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                            "default=noprint_wrappers=1:nokey=1", str(args.audio)], capture_output=True, text=True, check=True)
    seconds = float(probe.stdout.strip())
    timed_prompt = PROMPT + f"\n音频实际总长约 {seconds:.2f} 秒。时间戳必须是从 00:00 起的真实相对时间，绝不可超过该时长。音频结束即停止，勿循环末尾对话。"
    request_body = {"model": args.model, "temperature": 0, "max_tokens": 16000,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": timed_prompt},
                        {"type": "input_audio", "input_audio": {
                            "data": base64.b64encode(contents).decode("ascii"), "format": "mp3"}}]}]}
    request = urllib.request.Request(args.url, data=json.dumps(request_body).encode(),
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        # A short status is safe to show; never print the bearer token or request body.
        raise RuntimeError(f"Cloud route returned HTTP {error.code}: {error.read(500).decode(errors='replace')}") from None
    content = result["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Cloud route returned no transcript text")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "gemini-transcript.md").write_text(
        f"# Gemini 云端音频对照（未经人工校对）\n\n> 模型：{args.model}；输入为连续音频；未提供 Plaud 稿作为提示。\n\n" + content.strip() + "\n")
    summary = {"audio_sha256": hashlib.sha256(contents).hexdigest(), "model": args.model,
               "elapsed_seconds": round(time.monotonic() - started, 2),
               "usage": result.get("usage"), "route": args.url,
               "finish_reason": result["choices"][0].get("finish_reason")}
    (args.output / "gemini-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
