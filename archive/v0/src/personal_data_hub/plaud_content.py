"""把 Plaud 处理产物归档为可查询正文；未完成的单源稿明确标为草稿。"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts import Asset, Record, instant


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def stamp(seconds):
    n = int(seconds)
    return f"{n // 3600:02d}:{n % 3600 // 60:02d}:{n % 60:02d}"


class PlaudContent:
    def __init__(self, root, timezone="Asia/Shanghai"):
        self.root = Path(root)
        self.daily = self.root / "daily-v3"
        self.zone = timezone
        self.statuses = {}
        for path in (self.daily / "status").glob("*.json"):
            status = read_json(path)
            if status.get("date"): self.statuses[status["date"]] = status
        latest = read_json(self.daily / "latest.json")
        if latest.get("date"): self.statuses[latest["date"]] = latest
        self.extra_records = []
        self.days = {}
        days = set(self.statuses)
        days.update(p.name[:10] for p in (self.daily / "output").glob("*.md"))
        for day in sorted(days):
            status = self.statuses.get(day, {})
            transcript_path = self.daily / "output" / f"{day}.md"
            summary_path = self.daily / "output" / f"{day}.summary.md"
            draft = not transcript_path.is_file() and (self.daily / "output" / f"{day}.draft.md").is_file()
            if draft:
                transcript_path = self.daily / "output" / f"{day}.draft.md"
                summary_path = self.daily / "output" / f"{day}.draft-summary.md"
            transcript = transcript_path.read_text() if transcript_path.is_file() else ""
            summary = summary_path.read_text() if summary_path.is_file() else ""
            self.days[day] = {"transcript": transcript, "summary": summary, "draft": draft,
                              "status": status.get("status", "complete" if summary else "waiting_summary")}
            occurred = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(self.zone))
            updated = instant(status.get("checked_at"))
            if status:
                self.extra_records.append(Record("processing:" + day, "recording_processing_status", status,
                    {"date": day, "title": "Plaud 处理状态 · " + day, "status": status["status"], "engine": status.get("engine"),
                     "summary_status": (status.get("summary") or {}).get("status"), "content": status["status"]}, occurred, updated, self.zone))
            for label, kind, content, path in [("daily_report", "recording_daily_report", transcript, transcript_path),
                                                ("summary", "recording_summary", summary, summary_path)]:
                if not content: continue
                self.extra_records.append(Record(label + ":" + day, kind, {"path": str(path.relative_to(self.root))},
                    {"date": day, "title": ("Plaud 录音日报 · " if label == "daily_report" else "Plaud 日报摘要 · ") + day,
                     "content": content, "summary": summary, "status": "draft" if draft else "complete", "draft": draft,
                     "scope": "day", "derived_from_recording_date": day},
                    occurred, updated, self.zone, [Asset(path.name, path=path, media_type="text/markdown")]))

    def recording(self, row):
        fid, day = row["recording_id"], row["local_date"]
        expected = math.ceil(row["duration_ms"] / 1200000)
        candidates = []
        for folder in (self.daily / "sources" / fid).glob("*"):
            blocks = []
            for p in sorted(folder.glob("*/sample.json")):
                sample = read_json(p)
                if sample.get("recording_id") == fid and sample.get("source_sha256") == row.get("sha256"):
                    blocks.append((p.parent, sample))
            if blocks: candidates.append(blocks)
        blocks = max(candidates, key=lambda bs: (len(bs), max(p.stat().st_mtime_ns for p, _ in bs)), default=[])
        sources = {}
        for engine in ("groq_whisper", "gemini", "sensevoice"):
            segments, texts, completed = [], [], 0
            invalid = False
            for folder, sample in blocks:
                offset, seconds = sample["offset_seconds"], sample["duration_seconds"]
                name = {"groq_whisper": "groq-whisper-large-v3", "gemini": "gemini", "sensevoice": "sensevoice"}[engine]
                meta = read_json(folder / (name + "-summary.json"))
                if meta.get("audio_sha256") != sample["audio_sha256"]: continue
                found = []
                if engine == "groq_whisper":
                    wire = read_json(folder / (name + ".json"))
                    if abs(float(wire.get("duration", 0)) - seconds) > 1: continue
                    found = [{"start_seconds": offset + float(s["start"]), "end_seconds": offset + float(s["end"]), "text": s["text"]}
                             for s in wire.get("segments", [])]
                elif engine == "sensevoice":
                    path = folder / "sensevoice-fixed.jsonl"
                    if not path.is_file(): continue
                    found = [{**s, "start_seconds": offset + s["start_seconds"], "end_seconds": offset + s["end_seconds"]}
                             for s in (json.loads(line) for line in path.read_text().splitlines() if line.strip())]
                else:
                    path = folder / "gemini-transcript.md"
                    if not path.is_file() or meta.get("finish_reason") != "stop": continue
                    matches = list(re.finditer(r"^\s*(?:[-*]\s*)?\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*Speaker\s+([\d?]+)\s*[:：]\s*(.+)$", path.read_text(), re.M))
                    starts = [int(m[1]) * 60 + int(m[2]) if m[3] is None else int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) for m in matches]
                    invalid |= not starts or any(n >= seconds for n in starts) or starts != sorted(starts)
                    found = [{"start_seconds": offset + n, "speaker": f"b{sample['block_index']:03d}/{m[4]}", "text": m[5]} for n, m in zip(starts, matches)]
                if not found: continue
                completed += 1
                segments.extend(found)
                texts.extend(f"[{stamp(s['start_seconds'])}] " + (f"Speaker {s['speaker']}: " if s.get("speaker") else "") + s["text"] for s in found)
            if not texts: continue
            # 分块库存和偏移必须连续；不能把缺尾块的稿声明为完整。
            offsets = sorted(s["offset_seconds"] for _, s in blocks)
            covered = len(blocks) == expected and offsets == [i * 1200 for i in range(expected)] and abs(sum(s["duration_seconds"] for _, s in blocks) - row["duration_ms"] / 1000) <= .1
            state = "invalid_timestamps" if invalid else ("complete" if completed == expected and covered else "partial")
            source = {"engine": engine, "status": state, "draft": True, "blocks": completed, "expected_blocks": expected,
                      "content": "\n".join(texts), "segments": segments}
            sources[engine] = source
            self.extra_records.append(Record(f"transcript:{fid}:{engine}", "recording_transcript",
                {"recording_id": fid, "source_sha256": row["sha256"]}, {**source, "date": day, "title": f"Plaud 转录草稿 · {day} · {engine}"},
                instant(row["start_at"]), None, self.zone, [Asset(f"{fid}-{engine}.md", content=source["content"].encode(), media_type="text/markdown")]))
        legacy = self.root / "work" / fid / "transcript.md"
        if legacy.is_file():
            text = legacy.read_text()
            sources["legacy_selected"] = {"engine": "legacy_selected", "status": "partial", "draft": True,
                                          "scope": "selected_segments", "content": text}
            self.extra_records.append(Record(f"transcript:{fid}:legacy_selected", "recording_transcript",
                {"recording_id": fid, "path": str(legacy.relative_to(self.root))},
                {**sources["legacy_selected"], "date": day, "title": "Plaud 历史片段转录 · " + day}, instant(row["start_at"]), None,
                self.zone, [Asset(legacy.name, path=legacy, media_type="text/markdown")]))
        primary = next((sources[e] for e in ("groq_whisper", "sensevoice", "gemini") if sources.get(e, {}).get("status") == "complete"), None)
        partial = next((sources[e] for e in ("groq_whisper", "sensevoice", "gemini", "legacy_selected") if sources.get(e, {}).get("status") == "partial"), None)
        readable = primary or partial or {}
        daily = self.days.get(day, {})
        fused = ""
        if daily.get("transcript") and not daily.get("draft"):
            sections = re.split(r"(?=^##\s+录音\s+)", daily["transcript"], flags=re.M)
            fused = next((s for s in sections if re.match(r"^##\s+录音\s+" + re.escape(fid) + r"(?:\s|$)", s)), "")
        return {"transcript": fused or readable.get("content", ""),
                "transcript_engine": "three_source_fusion" if fused else readable.get("engine"),
                "transcription_status": "complete" if fused else ("source_ready" if primary else ("source_partial" if partial else "pending")),
                "transcript_is_draft": not bool(fused), "transcripts": sources,
                "summary": daily.get("summary", ""), "summary_scope": "day", "summary_status": ("draft" if daily.get("draft") else "complete") if daily.get("summary") else "pending",
                "daily_report_external_id": "daily_report:" + day if daily.get("transcript") else None,
                "processing": self.statuses.get(day, {})}
