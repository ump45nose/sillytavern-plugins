"""One-shot decisive rewrite of the reviewed three-source Markdown.

The reviewed source and its overriding output requirement are one Markdown
message. This does not rerun ASR or consult another transcript. A request
sentinel prevents accidental retries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .fusion_v3 import CPA_URL, EXPERIMENT, MODEL, OUTPUT as REVIEW_OUTPUT, sha256_file, write_once, write_status


APPROVED_SHA256 = "b2afb7b823b5e9fa8f5f6a414e5d117a86edc4d48dbdb3fe967dd32e43e7d172"
OUTPUT = EXPERIMENT / "fusion-v4-decisive"
OVERRIDE_INSTRUCTION = """# 本次唯一输出要求（覆盖下文旧版的候选/警告规则）

你要直接交付一份确定性、好读的中文对话 Markdown。下文是已审阅的三源原始转写输入；完整阅读它，按时间覆盖 00:00–20:00。保持同一录音的 Speaker 1＝【我】、Speaker 2＝【他人】，保留每个主要话轮的相对时间戳，不凭文本语气重新分配身份。

本次输出方式覆盖下文要求“列出候选并标 🔴”的旧规则：数字、金额、比例、否定、人名、机构、术语及其他歧义都必须结合三源多数、上下文和语言常识，选出一个你认为最可能的确定说法。允许在来源分歧时自行推断，但不要编造来源中没有依据的新事实。不要输出候选列表、竖线、斜杠式二选一、🔴、问号身份标签、逐源对照、说明或审计附录。只有三源和上下文都无法支持任何通顺解释时，写 [听不清]；不要留下乱码。短附和词可合入相邻话轮。最终只返回一份 Markdown 对话稿。"""
TURN = re.compile(r"^\[(\d{2}):(\d{2})\]\s*【(我|他人)】", re.M)


def validate_answer(answer: str) -> dict:
    if answer.lstrip().startswith(("```", "{")):
        raise RuntimeError("response is not plain Markdown")
    if "🔴" in answer or "｜" in answer or "【我?】" in answer or "【他人?】" in answer:
        raise RuntimeError("response still contains alternatives or uncertain labels")
    if re.search(r"\[[^\]\n]*\|[^\]\n]*\]", answer):
        raise RuntimeError("response still contains bracketed alternatives")
    turns = [(int(m[1]) * 60 + int(m[2]), m[3]) for m in TURN.finditer(answer)]
    if len(turns) < 40 or min(t for t, _ in turns) > 30 or max(t for t, _ in turns) < 1170:
        raise RuntimeError("response does not cover the full 20-minute conversation")
    if not any(450 <= t <= 475 for t, _ in turns) or not any(700 <= t <= 730 for t, _ in turns):
        raise RuntimeError("response appears to omit a required middle section")
    return {"turns": len(turns), "first_second": min(t for t, _ in turns),
            "last_second": max(t for t, _ in turns)}


def submit_once() -> None:
    source = REVIEW_OUTPUT / "fusion-input-v3.md"
    if sha256_file(source) != APPROVED_SHA256:
        raise RuntimeError("reviewed Markdown changed; do not submit")
    key = os.environ.get("CPA_PUBLIC_API_KEY") or os.environ.get("CPA_OAUTH_API_KEY")
    if not key:
        raise RuntimeError("CPA credential is missing")
    OUTPUT.mkdir(mode=0o700, exist_ok=False)
    os.chmod(OUTPUT, 0o700)
    attempt_path = OUTPUT / "submission-attempt.json"
    complete_markdown = OVERRIDE_INSTRUCTION + "\n\n---\n\n" + source.read_text()
    input_path = OUTPUT / "fusion-input-v4-decisive.md"
    write_once(input_path, complete_markdown)
    status = {"status": "attempted_once", "source_sha256": APPROVED_SHA256,
              "submitted_markdown_sha256": sha256_file(input_path), "requested_model": MODEL,
              "override_instruction_sha256": hashlib.sha256(OVERRIDE_INSTRUCTION.encode()).hexdigest()}
    write_once(attempt_path, json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    body = {"model": MODEL, "temperature": 0, "max_tokens": 12000,
            "messages": [{"role": "user", "content": complete_markdown}]}
    request = urllib.request.Request(CPA_URL, data=json.dumps(body, ensure_ascii=False).encode(),
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.load(response)
        choice = result["choices"][0]
        answer = choice["message"].get("content")
        if not isinstance(answer, str) or not answer.strip() or choice.get("finish_reason") != "stop":
            raise RuntimeError("CPA response is incomplete")
        write_once(OUTPUT / "response-unvalidated.md", answer.rstrip() + "\n")
        usage = result.get("usage")
        metadata = {"served_model": result.get("model"), "usage": usage,
                    "finish_reason": choice.get("finish_reason"), "elapsed_seconds": round(time.monotonic() - started, 1)}
        write_once(OUTPUT / "response-metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        validation = validate_answer(answer)
    except Exception as error:
        description = f"HTTP {error.code}" if isinstance(error, urllib.error.HTTPError) else str(error)
        status.update({"status": "failed", "error": description[:500],
                       "elapsed_seconds": round(time.monotonic() - started, 1)})
        write_status(attempt_path, status)
        raise RuntimeError(f"single request failed; no retry sent: {description}") from None
    footer = (f"\n\n---\n原始输入 SHA-256：`{APPROVED_SHA256}`；本次提交 Markdown SHA-256：`{status['submitted_markdown_sha256']}`；请求模型：`{MODEL}`；"
              f"实际服务模型：`{metadata['served_model'] or '未返回'}`；耗时：{metadata['elapsed_seconds']} 秒；"
              f"实际用量：`{json.dumps(usage, ensure_ascii=False) if isinstance(usage, dict) else 'CPA 未返回'}`。\n")
    final_path = OUTPUT / "transcript-decisive.md"
    write_once(final_path, answer.rstrip() + footer)
    status.update({"status": "complete", "validation": validation, "metadata": metadata,
                   "final_sha256": sha256_file(final_path)})
    write_status(attempt_path, status)
    print(json.dumps({"status": "complete", "path": str(final_path),
                      "sha256": status["final_sha256"], "validation": validation}, ensure_ascii=False))


if __name__ == "__main__":
    submit_once()
