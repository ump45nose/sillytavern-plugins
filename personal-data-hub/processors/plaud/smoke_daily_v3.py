"""One local smoke: full coverage, tail block, cache and one-request fence.

Uses synthetic audio and stub responses; no network or real ASR is invoked.
"""
import io
import json
import math
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from plaud_daily import daily_v3 as daily
from plaud_daily import multiday_trial as trial
from plaud_daily.core import atomic_bytes, load_config


def json_file(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False) + "\n").encode())


with tempfile.TemporaryDirectory(prefix="plaud-v3-smoke-") as directory:
    base = Path(directory)
    source = base / "input"
    source.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
                    "-t", "1225", "-b:a", "32k", str(source / "audio.mp3")], check=True)
    json_file(source / "recording.json", {"recording_id": "smoke_recording", "start_at": "2026-10-05T00:00:00Z",
                                         "duration_ms": 1225000, "path": "audio.mp3"})
    config = load_config()
    config.update(data_root=str(base / "data"), sync_provider="local_dir", local_dir=str(source))
    workflow = {"data_root": config["data_root"], "scope": "full_recordings", "fusion_mode": "auto_validated",
                "fusion_model": "grok-4.7", "cpa_url": "http://unused.invalid", "max_input_bytes": 750000}
    prepared, requests = [], []

    def fake_cloud(engine, chunks, *, root):
        for key in chunks:
            folder = root / key
            seconds = json.loads((folder / "sample.json").read_text())["duration_seconds"]
            digest = trial.verify_audio(folder)
            prepared.append((engine, key))
            if engine == "gemini":
                trial.write_once(folder / "gemini-transcript.md", "[00:00] Speaker 1: 数字123。\n")
                json_file(folder / "gemini-summary.json", {"audio_sha256": digest, "finish_reason": "stop"})
            else:
                json_file(folder / "groq-whisper-large-v3.json", {"duration": seconds,
                          "segments": [{"start": 0, "end": seconds, "text": "数字123。"}]})
                json_file(folder / "groq-whisper-large-v3-summary.json", {"audio_sha256": digest})

    def fake_sv(config, chunks, *, root):
        for key in chunks:
            folder = root / key
            seconds = json.loads((folder / "sample.json").read_text())["duration_seconds"]
            rows = [{"start_seconds": n * 25, "end_seconds": min(seconds, (n + 1) * 25), "text": "数字123。"}
                    for n in range(math.ceil(seconds / 25))]
            trial.write_once(folder / "sensevoice-fixed.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            json_file(folder / "sensevoice-summary.json", {"audio_sha256": trial.verify_audio(folder)})

    def fake_post(request, **kwargs):
        body = json.loads(request.data)
        assert len(body["messages"]) == 1
        if "主要内容" in body["messages"][0]["content"]:
            requests.append(body)
            return io.BytesIO(json.dumps({"model": "grok-4.7", "choices": [{"finish_reason": "stop", "message": {
                "content": "## 主要内容\n数字123。\n## 决定与待办\n未提及。\n## 待确认\n说话人身份。"}}]}).encode())
        assert "smoke_recording-b001" in body["messages"][0]["content"]
        assert "smoke_recording-b002" in body["messages"][0]["content"]
        requests.append(body)
        return io.BytesIO(json.dumps({"model": "grok-4.7", "usage": {"total_tokens": 1}, "choices": [
            {"finish_reason": "stop", "message": {"content": "## 录音 smoke_recording\n\n[00:00] Speaker b001/1: 数字123。\n[20:00] Speaker b002/1: 数字123。"}}]}).encode())

    with patch.object(trial, "cloud", fake_cloud), patch.object(trial, "sensevoice", fake_sv), \
         patch.object(trial, "configured_key", return_value="smoke-not-a-real-key"), \
         patch.object(daily.urllib.request, "urlopen", side_effect=fake_post):
        result = daily.run_date(workflow, config, "2026-10-05", finalize=False)
        assert result["status"] == "waiting_finalize" and result["blocks"] == 2
        assert not requests
        root = Path(result["run"])
        tail = json.loads((root / "smoke_recording-b002/sample.json").read_text())
        assert tail["offset_seconds"] == 1200 and tail["duration_seconds"] == 25
        result = daily.run_date(workflow, config, "2026-10-05", finalize=True)
        assert result["status"] == "complete" and len(requests) == 2
        again = daily.run_date(workflow, config, "2026-10-05", finalize=True)
        assert again["status"] == "complete" and len(requests) == 2 and len(prepared) == 4
        original_sha = trial.sha256_file
        with patch.object(trial, "sha256_file", side_effect=lambda p: "f" * 64 if Path(p).resolve() == Path(daily.__file__).resolve() else original_sha(p)):
            updated = daily.run_date(workflow, config, "2026-10-05", finalize=True)
        assert updated["status"] == "complete" and updated["run"] == str(root)
        assert len(requests) == 2 and len(prepared) == 4
        cached = daily.submit_approved(workflow, root, result["input_sha256"], automatic=True, day="2026-10-05")
        assert cached["status"] == "complete"
        assert len(requests) == 2
        assert (Path(config["data_root"]) / "output/2026-10-05.md").is_file()
        assert (Path(config["data_root"]) / "output/2026-10-05.summary.md").is_file()

    # Gemini 不可用也保留完整单源稿和摘要草稿；不得提交伪三源融合。
    partial_config = {**config, "data_root": str(base / "partial")}
    partial_workflow = {**workflow, "data_root": partial_config["data_root"]}
    def missing_gemini(engine, chunks, *, root):
        if engine == "groq": fake_cloud(engine, chunks, root=root)
    with patch.object(trial, "cloud", missing_gemini), patch.object(trial, "sensevoice", fake_sv), \
         patch.object(trial, "configured_key", return_value="smoke-not-a-real-key"), \
         patch.object(daily.urllib.request, "urlopen", side_effect=fake_post):
        before = len(requests)
        result = daily.run_date(partial_workflow, partial_config, "2026-10-05")
        assert result["status"] == "source_retry_pending" and result["draft"]
        assert result["summary"]["status"] == "complete" and len(requests) == before + 1
        assert not (Path(result["run"]) / "transcript-v3.md").exists()
        assert (Path(partial_config["data_root"]) / "output/2026-10-05.draft-summary.md").is_file()
        again = daily.run_date(partial_workflow, partial_config, "2026-10-05")
        assert len(requests) == before + 1 and again["draft"]

inventory = [{"id": "recording", "duration_ms": 7200000}]
daily.validate_fused_response("## 录音 recording\n**00:00:02 Speaker 1**\n原话\n**01:59:59 Speaker 2**\n原话", inventory)
unknown = '## 录音 recording\n**00:00:02** 原话\n[01:59:59.250] 原话'
normalized = daily.normalize_fused_response(unknown)
assert normalized == '## 录音 recording\n**00:00:02** Speaker ?: 原话\n[01:59:59.250] Speaker ?: 原话'
daily.validate_fused_response(normalized, inventory)
known = '## 录音 recording\n[00:02]  Speaker 1: 原话'
assert daily.normalize_fused_response(known) == known
for bad in ("## 录音 recording\n只有日期 2026-10-08T15:31:59", "## 录音 recording\n**02:00:00 Speaker 1**\n越界", "## 录音 recording\n[00:02] Speaker 1: 原话\n[00:01] Speaker 2: 倒序", "## 录音 recording\n[00:01] Speaker 1: 【他人?】"):
    try: daily.validate_fused_response(bad, inventory)
    except RuntimeError: pass
    else: raise AssertionError("Invalid fusion response accepted")
print("smoke OK: full/tail coverage, cached rerun after runner update, single fusion/summary, honest drafts and fusion timestamp boundaries; no network")
