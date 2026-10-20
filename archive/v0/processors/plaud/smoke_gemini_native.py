"""验证 Gemini 响应边界和时间戳规范化；不调用网络。"""
import hashlib
import json
import tempfile
from pathlib import Path

from plaud_daily.gemini_native import normalize_timestamp_brackets, publish_response


def response(text, finish="STOP"):
    return {"candidates": [{"finishReason": finish, "content": {"parts": [
        {"text": "内部推理不应归档", "thought": True}, {"text": text}]}}]}


text = "00:01 Speaker 1: 数字1.0。\n[00:03] Speaker ?: [听不清]\n- 00:09 Speaker 2: 保留原话。"
expected = "[00:01] Speaker 1: 数字1.0。\n[00:03] Speaker ?: [听不清]\n- [00:09] Speaker 2: 保留原话。"
assert normalize_timestamp_brackets(text) == expected
assert normalize_timestamp_brackets(expected) == expected
with tempfile.TemporaryDirectory(prefix="plaud-gemini-smoke-") as folder:
    root = Path(folder)
    good = root / "good"
    summary = publish_response(b"same-audio", good, "gemini-pro-agent", response(text), 30, 1.5)
    assert summary["audio_sha256"] == hashlib.sha256(b"same-audio").hexdigest()
    assert summary["timing"]["valid"] and summary["timestamp_brackets_normalized"]
    assert (good / "gemini-raw-transcript.md").read_text() == text + "\n"
    assert (good / "gemini-transcript.md").read_text().endswith(expected + "\n")
    assert "内部推理" not in (good / "gemini-transcript.md").read_text()
    cases = {
        "blocked": {"promptFeedback": {"blockReason": "OTHER", "blockReasonMessage": "full diagnostic"}},
        "truncated": response("[00:01] Speaker 1: 未完成", "MAX_TOKENS"),
        "out_of_range": response("[00:30] Speaker 1: 不裁剪时间"),
        "backwards": response("[00:09] Speaker 1: 原话\n[00:01] Speaker 2: 原话"),
        "no_timestamps": response("只有说明，不是带时间的逐字稿"),
    }
    for name, wire in cases.items():
        output = root / name
        try:
            publish_response(b"same-audio", output, "gemini-pro-agent", wire, 30, 1.5)
        except RuntimeError:
            pass
        else:
            raise AssertionError(name + " must fail")
        assert not (output / "gemini-summary.json").exists()
        assert not (output / "gemini-transcript.md").exists()
    diagnostic = json.loads((root / "blocked/gemini-response-diagnostic.json").read_text())
    assert diagnostic["prompt_feedback"]["blockReasonMessage"] == "full diagnostic"
print("smoke OK: exact timestamp bracketing, raw preservation, blocked/truncated/invalid source rejection; no network")
