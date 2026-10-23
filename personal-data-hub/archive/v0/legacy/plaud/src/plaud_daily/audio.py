"""Bounded-memory audio normalization and decoding."""

from __future__ import annotations

import os
import json
import struct
import subprocess
from pathlib import Path

import numpy as np

from .core import RRException, atomic_bytes, sha256_file


def _ogg_crc(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04C11DB7 if value & 0x80000000 else 0)) & 0xFFFFFFFF
    return value


def _ogg_page(packets: list[bytes], serial: int, sequence: int, granule: int, flags: int) -> bytes:
    segments = [part for packet in packets for part in ([255] * (len(packet) // 255) + [len(packet) % 255])]
    header = b"OggS" + bytes((0, flags)) + struct.pack("<QII", granule, serial, sequence) + b"\0\0\0\0" + bytes((len(segments),)) + bytes(segments)
    page = header + b"".join(packets)
    return page[:22] + struct.pack("<I", _ogg_crc(page)) + page[26:]


def normalize(row, root: Path) -> Path:
    source = Path(row["local_path"])
    if not source.is_file() or sha256_file(source) != row["sha256"]:
        raise RRException("raw_missing_or_changed", "Raw recording is absent or hash differs")
    if row["media_format"] != "opusraw":
        return source
    out = root / "work" / row["recording_id"] / "audio.opus"
    marker = out.with_suffix(".sha256")
    if out.is_file() and marker.is_file():
        try:
            saved = json.loads(marker.read_text())
            if saved["raw_sha256"] == row["sha256"] and saved["normalized_sha256"] == sha256_file(out):
                return out
        except (ValueError, KeyError):
            pass
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".part")
    serial = int(row["sha256"][:8], 16)
    sequence = 0
    granule = 0
    with source.open("rb") as src, part.open("wb") as dst:
        os.chmod(part, 0o640)
        for packet in (b"OpusHead" + bytes((1, 1)) + struct.pack("<H", 312) + struct.pack("<I", 48000) + b"\0\0\0", b"OpusTags" + struct.pack("<I", 11) + b"plaud-daily" + struct.pack("<I", 0)):
            dst.write(_ogg_page([packet], serial, sequence, 0, 2 if sequence == 0 else 0))
            sequence += 1
        while chunk := src.read(80 * 128):
            if len(chunk) % 80:
                raise RRException("unsupported_audio_contract", "Raw Opus frame boundary changed")
            packets = []
            for pos in range(0, len(chunk), 80):
                packet = chunk[pos:pos + 80]
                if packet[0] != 0xB8:
                    raise RRException("unsupported_audio_contract", "Raw Opus frame TOC changed")
                granule += 960
                packets.append(packet)
            final = src.tell() == source.stat().st_size
            dst.write(_ogg_page(packets, serial, sequence, granule, 4 if final else 0))
            sequence += 1
        dst.flush()
        os.fsync(dst.fileno())
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(part)], capture_output=True, text=True)
    if probe.returncode or not probe.stdout.strip():
        part.unlink(missing_ok=True)
        raise RRException("unsupported_audio_contract", "Normalized Ogg Opus failed probe")
    os.replace(part, out)
    atomic_bytes(marker, (json.dumps({"raw_sha256": row["sha256"], "normalized_sha256": sha256_file(out)}) + "\n").encode())
    return out


def ffmpeg_stream(path: Path, *, start_ms: int = 0, duration_ms: int | None = None):
    command = ["ffmpeg", "-v", "error", "-nostdin", "-threads", "1"]
    if start_ms:
        command += ["-ss", f"{start_ms / 1000:.3f}"]
    command += ["-i", str(path)]
    if duration_ms is not None:
        command += ["-t", f"{duration_ms / 1000:.3f}"]
    command += ["-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"]
    return subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def read_slice(path: Path, start_ms: int, end_ms: int) -> np.ndarray:
    if end_ms <= start_ms or end_ms - start_ms > 65000:
        raise RRException("audio_slice_invalid", "Audio slice must be 0-65 seconds")
    process = ffmpeg_stream(path, start_ms=start_ms, duration_ms=end_ms - start_ms)
    data, error = process.communicate()
    if process.returncode:
        raise RRException("audio_decode_failed", error.decode(errors="replace")[:200])
    return np.frombuffer(data, dtype="<f4").copy()
