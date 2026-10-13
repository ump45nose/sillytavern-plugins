"""Export reviewable, lossless gold clips without treating model output as truth."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .audio import normalize
from .core import RRException, State, atomic_bytes, data_root, load_config, now_iso, read_jsonl, sha256_file
from .sync import parse_utc


SCENES = (
    ("meeting-2026-09-24", "of_dfd11c9e7a7b15f3e15da0c9a45b298b", "2026-09-24T10:32:00"),
    ("chat-2026-09-26", "of_0b2bb36d9181ddc260119e402bce1a42", "2026-09-26T13:47:00"),
    ("car-2026-09-26", "of_0b2bb36d9181ddc260119e402bce1a42", "2026-09-26T12:05:00"),
)
DURATION_MS = 600_000
FIELDS = ("start_ms", "end_ms", "candidate_speaker", "candidate_text", "gold_speaker", "gold_text", "exclude", "notes")
ENROLLMENT_INDEX = 139


def _audio_export(source: Path, output: Path, start_ms: int, codec: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".gold-", suffix=".part", delete=False) as out:
        part = Path(out.name)
    try:
        os.chmod(part, 0o640)
        command = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{start_ms / 1000:.3f}", "-i", str(source), "-t", "600", "-ac", "1", "-ar", "16000"]
        command += ["-c:a", "pcm_s16le", "-f", "wav"] if codec == "wav" else ["-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3"]
        run = subprocess.run([*command, str(part)], capture_output=True, text=True)
        if run.returncode or part.stat().st_size == 0:
            raise RRException("gold_export_failed", (run.stderr or "FFmpeg produced empty audio")[:300])
        with part.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(part, output)
    finally:
        part.unlink(missing_ok=True)


def _tsv(rows: list[dict]) -> bytes:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def export(config: dict) -> list[dict]:
    root = data_root(config)
    state = State(root)
    result = []
    try:
        zone = ZoneInfo(config["timezone"])
        for scene, recording_id, local_start in SCENES:
            row = state.get_recording(recording_id)
            if not row or row["remote_state"] != "downloaded":
                raise RRException("gold_source_missing", f"Recording unavailable for {scene}")
            source = normalize(row, root)
            origin = parse_utc(row["start_at"])
            start = datetime.fromisoformat(local_start).replace(tzinfo=zone)
            offset_ms = round((start - origin).total_seconds() * 1000)
            if offset_ms < 0 or offset_ms + DURATION_MS > row["duration_ms"]:
                raise RRException("gold_window_invalid", scene)
            target = root / "gold/v1" / scene
            manifest_path = target / "manifest.json"
            if manifest_path.exists():
                old = json.loads(manifest_path.read_text())
                if old.get("source_sha256") != row["sha256"] or old.get("start_ms") != offset_ms:
                    raise RRException("gold_export_conflict", f"Existing scene differs: {scene}")
                for name in ("audio.wav", "audio.mp3", "annotations.tsv"):
                    if not (target / name).is_file():
                        raise RRException("gold_export_incomplete", f"Missing {scene}/{name}")
                result.append({"scene": scene, "path": str(target), "skipped": True})
                continue
            target.mkdir(parents=True, exist_ok=True, mode=0o750)
            _audio_export(source, target / "audio.wav", offset_ms, "wav")
            _audio_export(source, target / "audio.mp3", offset_ms, "mp3")
            excluded = []
            if scene == "chat-2026-09-26":
                segments = read_jsonl(root / "work" / recording_id / "segments.jsonl")
                enrollment = segments[ENROLLMENT_INDEX]
                if enrollment["segment_id"] != f"{recording_id}:{ENROLLMENT_INDEX:05d}":
                    raise RRException("gold_enrollment_changed", "Enrollment segment index changed")
                excluded.append([enrollment["start_ms"] - offset_ms, enrollment["end_ms"] - offset_ms])
            old_asr = root / "work" / recording_id / "asr.jsonl"
            candidates = []
            if old_asr.is_file():
                for item in read_jsonl(old_asr):
                    left = max(offset_ms, item["start_ms"])
                    right = min(offset_ms + DURATION_MS, item["end_ms"])
                    if right <= left:
                        continue
                    candidates.append({"start_ms": left - offset_ms, "end_ms": right - offset_ms,
                                       "candidate_speaker": item["speaker_label"], "candidate_text": item["text"].replace("\t", " ").replace("\n", " "),
                                       "gold_speaker": "", "gold_text": "", "exclude": "1" if any(left - offset_ms < end and right - offset_ms > start for start, end in excluded) else "", "notes": "注册样本，不计评分" if any(left - offset_ms < end and right - offset_ms > start for start, end in excluded) else ""})
            candidates.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
            annotation_path = target / "annotations.tsv"
            if not annotation_path.exists():
                atomic_bytes(annotation_path, _tsv(candidates))
            manifest = {"schema_version": 1, "status": "awaiting_human_review", "scene": scene,
                        "recording_id": recording_id, "source_sha256": row["sha256"], "source_path": str(source),
                        "local_start": start.isoformat(), "start_ms": offset_ms, "duration_ms": DURATION_MS,
                        "excluded_enrollment_intervals_ms": excluded,
                        "wav_sha256": sha256_file(target / "audio.wav"), "mp3_sha256": sha256_file(target / "audio.mp3"),
                        "candidate_rows": len(candidates)}
            guide = [f"# 金标核听 · {scene}", "", "候选说话人和文字来自旧模型，**不是人工真值**。请逐句核听、改写 annotations.tsv 的 gold_speaker/gold_text；必要时拆分、合并或新增行，尤其检查旧 VAD 漏掉的语音。", "", "gold_speaker 可填 me、other、overlap、background、unintelligible；重叠双方可填相同时间的两行。听不清的文字不要猜，填 unintelligible。", "", "时间字段是本音频起点起算的毫秒；空白金标字段代表尚未核听，不能参与评分。13:52:02 注册段及任何与它重叠的行必须设 exclude=1。", "", f"- 开始：{start.isoformat()}", f"- 结束：{(start + timedelta(minutes=10)).isoformat()}", f"- [核听 MP3]({target / 'audio.mp3'})", f"- [无损 WAV]({target / 'audio.wav'})", f"- [待填标注]({annotation_path})", ""]
            atomic_bytes(target / "review.md", ("\n".join(guide)).encode())
            atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
            result.append({"scene": scene, "path": str(target), "candidate_rows": len(candidates), "wav_sha256": manifest["wav_sha256"], "skipped": False})
        return result
    finally:
        state.close()


def validate(config: dict) -> list[dict]:
    root = data_root(config)
    reports = []
    for scene, _, _ in SCENES:
        folder = root / "gold/v1" / scene
        manifest = json.loads((folder / "manifest.json").read_text())
        if sha256_file(folder / "audio.wav") != manifest["wav_sha256"]:
            raise RRException("gold_audio_changed", scene)
        with (folder / "annotations.tsv").open(newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        reviewed = 0
        for number, item in enumerate(rows, 2):
            try:
                left, right = int(item["start_ms"]), int(item["end_ms"])
            except (ValueError, TypeError) as exc:
                raise RRException("gold_annotation_invalid", f"{scene}:{number} invalid times") from exc
            if not 0 <= left < right <= DURATION_MS:
                raise RRException("gold_annotation_invalid", f"{scene}:{number} out of window")
            speaker = item["gold_speaker"].strip()
            if item["exclude"].strip() == "1":
                if not item["notes"].strip():
                    raise RRException("gold_annotation_invalid", f"{scene}:{number} excluded row needs a reason")
                reviewed += 1
                continue
            if not speaker:
                continue
            if speaker not in ("me", "other", "overlap", "background", "unintelligible"):
                raise RRException("gold_annotation_invalid", f"{scene}:{number} invalid speaker")
            if any(left < end and right > start for start, end in manifest["excluded_enrollment_intervals_ms"]):
                raise RRException("gold_enrollment_leak", f"{scene}:{number} overlaps enrollment")
            if speaker in ("me", "other") and not item["gold_text"].strip():
                raise RRException("gold_annotation_invalid", f"{scene}:{number} missing reference text")
            reviewed += 1
        reports.append({"scene": scene, "rows": len(rows), "reviewed": reviewed, "complete": bool(rows) and reviewed == len(rows)})
    return reports


def review(config: dict) -> list[dict]:
    root = data_root(config)
    result = []
    for scene, _, _ in SCENES:
        folder = root / "gold/v1" / scene
        manifest = json.loads((folder / "manifest.json").read_text())
        with (folder / "annotations.tsv").open(newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        lines = [f"# 金标核听 · {scene}", "", "> 以下文字和人物均为旧模型候选，不是人工真值。请听完整 10 分钟，直接编辑 annotations.tsv 的 gold_speaker/gold_text；可拆分、合并、新增或删除候选行。", "",
                 "两人重叠可填同时间范围的 me 与 other 两行；听不清填 unintelligible。注册样本行 exclude=1，不参与评估。", "",
                 f"开始：{manifest['local_start']} · WAV SHA-256：`{manifest['wav_sha256']}`", "",
                 f"[核听 MP3]({folder / 'audio.mp3'}) · [无损 WAV]({folder / 'audio.wav'}) · [待填标注 TSV]({folder / 'annotations.tsv'})", "", "## 旧稿候选", ""]
        for index, item in enumerate(rows, 1):
            millis = int(item["start_ms"])
            timestamp = f"{millis // 60000:02d}:{millis % 60000 // 1000:02d}"
            status = " [注册样本：排除]" if item["exclude"].strip() == "1" else ""
            candidate = item["candidate_text"].replace("\n", " ").strip() or "（无旧转写）"
            lines.append(f"- {index:03d} · {timestamp} · 旧标 {item['candidate_speaker']} · {candidate}{status}")
        path = folder / "review.md"
        atomic_bytes(path, ("\n".join(lines) + "\n").encode())
        result.append({"scene": scene, "path": str(path), "candidates": len(rows)})
    return result


def finalize(config: dict, scene: str) -> dict:
    reports = validate(config)
    selected = next(item for item in reports if item["scene"] == scene)
    if not selected["complete"]:
        raise RRException("gold_incomplete", "Review every candidate row and listen for missed speech first")
    folder = data_root(config) / "gold/v1" / scene
    annotations = folder / "annotations.tsv"
    marker = folder / "human-reviewed.json"
    payload = {"scene": scene, "reviewed_by": "user", "reviewed_at": now_iso(),
               "annotations_sha256": sha256_file(annotations), "declaration": "Full ten-minute audio was listened to; speaker and words were corrected, including missed speech."}
    atomic_bytes(marker, (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode())
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "validate", "review", "finalize"))
    parser.add_argument("--config")
    parser.add_argument("--scene", choices=[item[0] for item in SCENES])
    parser.add_argument("--confirmed-by-user", action="store_true", help="User has listened to the entire scene, not only prefilled candidates")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.action == "finalize":
        if not args.scene or not args.confirmed_by_user:
            parser.error("finalize requires --scene and --confirmed-by-user")
        result = finalize(config, args.scene)
    else:
        result = export(config) if args.action == "export" else review(config) if args.action == "review" else validate(config)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
