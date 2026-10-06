"""Plaud MCP and local directory recording ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .core import RRException, State, data_root, hash_json, now_iso, sha256_file


_OPEN = re.compile(r"<(untrusted-user-data-[^ >]+)(?:\s+[^>]*)?>")


def parse_mcp_json(result: Any) -> dict[str, Any]:
    if getattr(result, "isError", False):
        words = " ".join(getattr(block, "text", "") for block in result.content)
        if "Not authenticated" in words or "401" in words:
            raise RRException("auth_failed", "Plaud MCP is not authenticated", 2)
        raise RRException("mcp_error", words[:300] or "Plaud MCP tool failed", 3)
    text = "\n".join(getattr(block, "text", "") for block in result.content)
    for match in reversed(list(_OPEN.finditer(text))):
        closing = text.find(f"</{match.group(1)}>", match.end())
        if closing < 0:
            continue
        try:
            payload = json.loads(text[match.end():closing].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RRException("contract_changed", "Plaud MCP returned no tagged JSON object")


def parse_utc(raw: str) -> datetime:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise RRException("contract_changed", "Invalid Plaud timestamp") from exc
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise RRException("contract_changed", "Unsafe recording id in Plaud response")
    return value


def _safe_audio_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RRException("contract_changed", "Invalid Plaud audio URL")
    return url


def local_day(start_at: str, config: dict[str, Any]) -> str:
    return parse_utc(start_at).astimezone(ZoneInfo(config["timezone"])).date().isoformat()


def _probe_remote(url: str) -> tuple[int, str | None, str]:
    try:
        req = urllib.request.Request(url, headers={"Range": "bytes=0-0", "User-Agent": "plaud-daily/0.1"})
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status != 206:
                raise RRException("range_unsupported", "Audio endpoint ignored byte range", 3)
            match = re.fullmatch(r"bytes 0-0/(\d+)", response.headers.get("Content-Range", ""))
            if not match:
                raise RRException("contract_changed", "Audio endpoint omitted total size")
            return int(match.group(1)), response.headers.get("ETag"), response.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RRException("upstream_temporary", "Could not probe Plaud audio URL", 3) from exc


def _validate_media(path: Path, mime: str, duration_ms: int, config: dict[str, Any]) -> str:
    if mime.startswith("audio/opus"):
        frame_size = int(config["audio"]["opus_frame_bytes"])
        frame_ms = int(config["audio"]["opus_frame_ms"])
        size = path.stat().st_size
        if not size or size % frame_size:
            raise RRException("unsupported_audio_contract", "Raw Opus frame size changed")
        frame_count = 0
        with path.open("rb") as src:
            while chunk := src.read(frame_size * 8192):
                if len(chunk) % frame_size or any(chunk[i] != 0xB8 for i in range(0, len(chunk), frame_size)):
                    raise RRException("unsupported_audio_contract", "Raw Opus frame TOC changed")
                frame_count += len(chunk) // frame_size
        if abs(frame_count * frame_ms - duration_ms) > max(200, frame_ms * 4):
            raise RRException("unsupported_audio_contract", "Raw Opus duration differs from metadata")
        return "opusraw"
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration", "-of", "json", str(path)], capture_output=True, text=True)
    if result.returncode:
        raise RRException("unsupported_audio_contract", "ffprobe could not identify downloaded audio")
    details = json.loads(result.stdout).get("format", {})
    actual_ms = float(details.get("duration", "0")) * 1000
    if actual_ms <= 0 or abs(actual_ms - duration_ms) > max(1000, duration_ms * 0.02):
        raise RRException("audio_duration_mismatch", "Downloaded audio duration differs from metadata")
    return "mp3" if "mp3" in details.get("format_name", "").split(",") else "media"


def _download(url: str, raw_dir: Path, recording_id: str, duration_ms: int, expected: int, mime: str, config: dict[str, Any]) -> tuple[Path, str, int, str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    staging = raw_dir / ".staging"
    staging.mkdir(parents=True, exist_ok=True)
    maximum = int(config["audio"]["max_download_bytes"])
    if expected <= 0 or expected > maximum:
        raise RRException("audio_size_invalid", "Plaud audio size is outside configured limit")
    digest = hashlib.sha256()
    size = 0
    with tempfile.NamedTemporaryFile(dir=staging, prefix=f"{recording_id}.", suffix=".part", delete=False) as output:
        part = Path(output.name)
        os.chmod(part, 0o640)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "plaud-daily/0.1"}), timeout=60) as response:
                if response.status != 200:
                    raise RRException("download_http_error", "Plaud audio download did not return HTTP 200", 3)
                reported = int(response.headers.get("Content-Length") or 0)
                if reported and reported != expected:
                    raise RRException("audio_size_changed", "Plaud audio length changed during download", 3)
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > maximum:
                        raise RRException("audio_size_invalid", "Plaud audio exceeded configured limit")
                    output.write(block)
                    digest.update(block)
            output.flush()
            os.fsync(output.fileno())
            if size != expected:
                raise RRException("download_truncated", "Downloaded size does not match Plaud Content-Range", 3)
            try:
                media_format = _validate_media(part, mime, duration_ms, config)
            except RRException as error:
                if not config.get("archive_only") or error.code != "unsupported_audio_contract": raise
                media_format = "media"
                from .core import atomic_bytes
                atomic_bytes(raw_dir / f"{recording_id}.archive-validation.json", json.dumps({"recording_id": recording_id, "status": "unverified_audio_contract", "reason": error.code, "mime": mime, "declared_duration_ms": duration_ms}).encode())
            final = raw_dir / f"{recording_id}.{media_format}"
            if final.exists() and sha256_file(final) != digest.hexdigest():
                history = raw_dir / ".history"
                history.mkdir(mode=0o750, exist_ok=True)
                shutil.move(final, history / f"{recording_id}.{sha256_file(final)[:16]}.{media_format}")
            os.replace(part, final)
            return final, digest.hexdigest(), size, media_format
        finally:
            part.unlink(missing_ok=True)


def _existing_raw(root: Path, recording_id: str, expected: int, mime: str, duration_ms: int, config: dict[str, Any]) -> tuple[Path, str, int, str] | None:
    for path in (root / "raw").glob(f"{recording_id}.*"):
        if path.suffix not in (".mp3", ".opusraw", ".media") or path.stat().st_size != expected:
            continue
        try:
            fmt = _validate_media(path, mime, duration_ms, config)
        except RRException:
            continue
        return path, sha256_file(path), expected, fmt
    return None


async def sync_plaud(config: dict[str, Any], state: State | None, *, target_date: str | None = None, recording_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    settings = config["plaud_mcp"]
    token = Path(settings["token_file"])
    if not token.is_file() or token.stat().st_mode & 0o077:
        raise RRException("auth_failed", "Plaud MCP token file is absent or too permissive", 2)
    params = StdioServerParameters(command=settings["command"], args=settings["args"])
    found = downloaded = reused = waiting = 0
    root = data_root(config)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            selected: list[dict[str, Any]] = []
            if recording_id:
                selected = [{"id": _safe_id(recording_id)}]
            else:
                cutoff = datetime.now(timezone.utc) - timedelta(days=int(settings["lookback_days"]))
                complete = False
                for page in range(1, int(settings["max_pages"]) + 1):
                    listing = parse_mcp_json(await session.call_tool("list_files", {"page": page, "page_size": int(settings["page_size"])}))
                    data = listing.get("data")
                    if not isinstance(data, list):
                        raise RRException("contract_changed", "list_files.data is not an array")
                    if not data:
                        complete = True
                        break
                    for item in data:
                        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("created_at"), str):
                            raise RRException("contract_changed", "list_files item schema changed")
                        _safe_id(item["id"])
                        if parse_utc(item["created_at"]) >= cutoff:
                            selected.append(item)
                    if min(parse_utc(item["created_at"]) for item in data) < cutoff:
                        complete = True
                        break
                if not complete:
                    raise RRException("pagination_incomplete", "Plaud pagination did not reach lookback boundary", 3)
            found = len(selected)
            for item in selected:
                fid = _safe_id(item["id"])
                detail = parse_mcp_json(await session.call_tool("get_file", {"file_id": fid}))
                if not all(key in detail for key in ("id", "start_at", "duration", "presigned_url")) or detail["id"] != fid:
                    raise RRException("contract_changed", "get_file response schema changed")
                if not dry_run:
                    from .core import atomic_bytes
                    archive_detail = {k: v for k, v in detail.items() if "presigned" not in k.lower() and "token" not in k.lower()}
                    atomic_bytes(root / "raw" / f"{fid}.source-metadata.json", json.dumps(archive_detail, ensure_ascii=False).encode())
                day = local_day(detail["start_at"], config)
                if target_date and day != target_date:
                    continue
                previous = state.get_recording(fid) if state is not None else None
                row = {"recording_id": fid, "source_provider": "plaud_mcp", "created_at": detail.get("created_at"), "start_at": detail["start_at"], "duration_ms": int(detail["duration"]), "local_date": day, "serial_number": detail.get("serial_number"), "remote_state": "seen", "local_path": previous["local_path"] if previous else None, "file_size": previous["file_size"] if previous else None, "sha256": previous["sha256"] if previous else None, "media_format": previous["media_format"] if previous else None, "remote_etag": previous["remote_etag"] if previous else None, "remote_size": previous["remote_size"] if previous else None, "downloaded_at": previous["downloaded_at"] if previous else None, "last_error": None}
                url = detail["presigned_url"]
                if not url:
                    waiting += 1
                    row["remote_state"] = "waiting_audio_url"
                    if not dry_run:
                        state.upsert_recording(row)
                        state.wait_stage("recording", fid, "sync", hash_json({"id": fid, "start": detail["start_at"]}), hash_json(settings), "waiting_audio_url")
                    continue
                url = _safe_audio_url(url)
                if dry_run:
                    continue
                expected, etag, mime = await asyncio.to_thread(_probe_remote, url)
                input_hash = hash_json({"id": fid, "etag": etag, "size": expected})
                config_hash = hash_json({"audio": config["audio"], "mcp_version": settings["args"]})
                old_valid = previous and etag and previous["remote_state"] == "downloaded" and previous["remote_etag"] == etag and previous["remote_size"] == expected and previous["local_path"] and Path(previous["local_path"]).is_file() and sha256_file(Path(previous["local_path"])) == previous["sha256"]
                if old_valid:
                    reused += 1
                    continue
                state.begin_stage("recording", fid, "sync", input_hash, config_hash)
                try:
                    existing = _existing_raw(root, fid, expected, mime, int(detail["duration"]), config) if not previous else None
                    artifact, sha, size, media_format = existing or await asyncio.to_thread(_download, url, root / "raw", fid, int(detail["duration"]), expected, mime, config)
                    if existing:
                        reused += 1
                    else:
                        downloaded += 1
                    row.update({"remote_state": "downloaded", "local_path": str(artifact), "file_size": size, "sha256": sha, "media_format": media_format, "remote_etag": etag, "remote_size": expected, "downloaded_at": now_iso()})
                    state.upsert_recording(row)
                    state.finish_stage("recording", fid, "sync", input_hash, config_hash, artifact, {"bytes": size, "media_format": media_format})
                except RRException as exc:
                    row.update({"remote_state": "failed", "last_error": exc.code})
                    state.upsert_recording(row)
                    state.fail_stage("recording", fid, "sync", input_hash, config_hash, exc)
                    raise
    return {"found": found, "downloaded": downloaded, "reused": reused, "waiting": waiting}


def sync_local_dir(config: dict[str, Any], state: State | None, *, target_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    source = config.get("local_dir")
    if not source or not Path(source).is_dir():
        raise RRException("local_dir_missing", "Configure an existing local_dir")
    found = downloaded = reused = 0
    root = data_root(config)
    for sidecar in sorted(Path(source).glob("*.json")):
        item = json.loads(sidecar.read_text())
        if not all(key in item for key in ("recording_id", "start_at", "duration_ms", "path")):
            raise RRException("local_contract_changed", f"Invalid local sidecar: {sidecar.name}")
        fid = str(item["recording_id"])
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", fid):
            raise RRException("recording_id_invalid", "Local recording id is unsafe")
        day = local_day(item["start_at"], config)
        if target_date and day != target_date:
            continue
        found += 1
        media = (Path(source) / item["path"]).resolve()
        if not media.is_file() or not media.is_relative_to(Path(source).resolve()):
            raise RRException("local_file_missing", f"Local media missing for {fid}")
        if dry_run:
            continue
        digest = sha256_file(media)
        ext = media.suffix.lower()
        if ext not in (".mp3", ".wav", ".m4a", ".opus"):
            raise RRException("local_format_invalid", "Unsupported local media extension")
        final = root / "raw" / (fid + ext)
        if final.exists() and sha256_file(final) == digest:
            reused += 1
        else:
            with tempfile.NamedTemporaryFile(dir=root / "raw/.staging", prefix=f"{fid}.", suffix=".part", delete=False) as stream:
                part = Path(stream.name)
                os.chmod(part, 0o640)
                with media.open("rb") as source_stream:
                    shutil.copyfileobj(source_stream, stream, 1024 * 1024)
                stream.flush()
                os.fsync(stream.fileno())
            if sha256_file(part) != digest:
                part.unlink(missing_ok=True)
                raise RRException("local_file_changed", "Local audio changed during copy")
            os.replace(part, final)
            downloaded += 1
        state.upsert_recording({"recording_id": fid, "source_provider": "local_dir", "created_at": item.get("created_at"), "start_at": item["start_at"], "duration_ms": int(item["duration_ms"]), "local_date": day, "serial_number": None, "remote_state": "downloaded", "local_path": str(final), "file_size": final.stat().st_size, "sha256": digest, "media_format": ext.lstrip("."), "remote_etag": None, "remote_size": final.stat().st_size, "downloaded_at": now_iso(), "last_error": None})
    return {"found": found, "downloaded": downloaded, "reused": reused, "waiting": 0}
