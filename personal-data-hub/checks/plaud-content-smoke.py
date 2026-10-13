"""检查完整分块、部分稿、日报关联、鉴权接口及幂等归档。"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from personal_data_hub.collectors import PlaudCollector
from personal_data_hub.contracts import Batch, Record, instant
from personal_data_hub.plaud_content import PlaudContent
from personal_data_hub.server import create_app
from personal_data_hub.storage import Store


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content) if isinstance(content, dict) else content)


with tempfile.TemporaryDirectory(prefix="plaud-content-") as directory:
    root = Path(directory)
    recording = {"recording_id": "recording1", "local_date": "2026-10-08", "start_at": "2026-10-08T00:00:00Z",
                 "duration_ms": 1225000, "sha256": "source-hash"}
    base = root / "daily-v3/sources/recording1/cache"
    for i, seconds in [(1, 1200), (2, 25)]:
        folder = base / f"recording1-b{i:03d}"
        write(folder / "sample.json", {"recording_id": "recording1", "source_sha256": "source-hash", "block_index": i,
                                      "offset_seconds": (i-1)*1200, "duration_seconds": seconds, "audio_sha256": "chunk-hash"})
        write(folder / "groq-whisper-large-v3-summary.json", {"audio_sha256": "chunk-hash"})
        write(folder / "groq-whisper-large-v3.json", {"duration": seconds, "segments": [{"start": 0, "end": seconds, "text": "测试文字"}]})
    write(root / "daily-v3/latest.json", {"date": "2026-10-08", "status": "source_failed_no_retry", "engine": "gemini"})
    content = PlaudContent(root).recording(recording)
    assert content["transcription_status"] == "source_ready" and content["transcript_is_draft"]
    assert "[00:20:00]" in content["transcript"] and content["processing"]["engine"] == "gemini"
    (base / "recording1-b002/groq-whisper-large-v3-summary.json").unlink()
    assert PlaudContent(root).recording(recording)["transcripts"]["groq_whisper"]["status"] == "partial"
    write(base / "recording1-b002/groq-whisper-large-v3-summary.json", {"audio_sha256": "wrong-hash"})
    assert PlaudContent(root).recording(recording)["transcription_status"] == "source_partial"
    write(base / "recording1-b002/groq-whisper-large-v3-summary.json", {"audio_sha256": "chunk-hash"})
    write(root / "daily-v3/output/2026-10-08.md", "## 录音 recording1 · 日期\n\n[00:00] 融合文字。\n\n## 录音 other\n\n另一条录音。")
    write(root / "daily-v3/output/2026-10-08.summary.md", "## 主要内容\n摘要正文。")
    archive = PlaudContent(root)
    content = archive.recording(recording)
    assert content["transcription_status"] == "complete" and not content["transcript_is_draft"]
    assert "另一条录音" not in content["transcript"] and content["summary_scope"] == "day"
    write(root / "daily-v3/output/2026-10-08.draft.md", "## 录音 recording1\n单源日报。")
    write(root / "daily-v3/output/2026-10-08.draft-summary.md", "摘要草稿。")
    (root / "daily-v3/output/2026-10-08.md").unlink()
    (root / "daily-v3/output/2026-10-08.summary.md").unlink()
    draft = PlaudContent(root).recording(recording)
    assert draft["transcript_is_draft"] and draft["summary_status"] == "draft"
    write(root / "daily-v3/output/2026-10-08.md", "## 录音 recording1 · 日期\n\n[00:00] 融合文字。\n\n## 录音 other\n\n另一条录音。")
    write(root / "daily-v3/output/2026-10-08.summary.md", "## 主要内容\n摘要正文。")
    store = Store("sqlite:///" + str(root / "archive.sqlite"), root / "assets")
    store.register("plaud", "owner", "plaud", "not_supported")
    batch = Batch(records=[Record("recording1", "recording", recording, {"date": "2026-10-08", **content}, instant(recording["start_at"]))] + archive.extra_records)
    first = store.ingest("plaud", batch)
    again = store.ingest("plaud", batch)
    assert first["changed"] == len(batch.records) and again["changed"] == 0
    rid = store.identity("plaud", "recording1")
    assert store.recording_content(rid)["daily_report"]["content"].startswith("## 录音 recording1")
    assert store.recording_content(store.identity("plaud", "summary:2026-10-08")) is None
    write(root / "viewer.token", "test-viewer")
    config = {"database_url": "sqlite://", "asset_root": str(root / "assets"), "sources": {}, "hub_viewer_token_file": str(root / "viewer.token")}
    with patch("personal_data_hub.server.store_from", return_value=store):
        app = create_app(config, webhook_only=True)
    client = TestClient(app)
    assert client.get(f"/api/v1/recordings/{rid}/content").status_code == 401
    result = client.get(f"/api/v1/recordings/{rid}/content", headers={"Authorization": "Bearer test-viewer"})
    assert result.status_code == 200 and result.json()["summary"] == content["summary"]
    assert client.get("/api/v1/recordings/missing/content", headers={"Authorization": "Bearer test-viewer"}).status_code == 404
print("plaud content smoke OK: source coverage, wrong-hash rejection, draft/final, linked summary, repeat ingest and authenticated API")
