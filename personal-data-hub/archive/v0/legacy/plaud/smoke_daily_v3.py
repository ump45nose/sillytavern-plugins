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
        assert result["status"] == "complete" and len(requests) == 1
        again = daily.run_date(workflow, config, "2026-10-05", finalize=True)
        assert again["status"] == "complete" and len(requests) == 1 and len(prepared) == 4
        try:
            daily.submit_approved(workflow, root, result["input_sha256"], automatic=True, day="2026-10-05")
        except FileExistsError:
            pass
        else:
            raise AssertionError("Repeated submission must be rejected")
        assert len(requests) == 1
        assert (Path(config["data_root"]) / "output/2026-10-05.md").is_file()

print("smoke OK: full 1225s coverage, 25s tail, cached rerun, one complete Markdown request; no network")
