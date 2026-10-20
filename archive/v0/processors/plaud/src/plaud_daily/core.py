"""Configuration, persistence, and atomic artifact helpers."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class RRException(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 1):
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".rr-", suffix=".part", delete=False) as out:
        tmp = Path(out.name)
        os.chmod(tmp, 0o640)
        out.write(value)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_bytes(path, ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)).encode())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_config(path: str | None = None) -> dict[str, Any]:
    source = Path(path or os.environ.get("RR_CONFIG", "/home/yuwk/.config/personal-data-hub/plaud-processing-base.yaml"))
    if not source.is_file():
        raise RRException("config_missing", f"Config not found: {source}")
    config = yaml.safe_load(source.read_text())
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise RRException("config_invalid", "Unsupported config schema")
    config["data_root"] = os.environ.get("RR_DATA_ROOT", config["data_root"])
    config["sync_provider"] = os.environ.get("RR_SYNC_PROVIDER", config["sync_provider"])
    config["timezone"] = os.environ.get("RR_TIMEZONE", config["timezone"])
    config["plaud_mcp"]["token_file"] = os.environ.get("RR_PLAUD_TOKEN_FILE", config["plaud_mcp"]["token_file"])
    context = config.get("context")
    asr = config.get("asr")
    if not isinstance(context, dict) or type(context.get("me_window_minutes")) is not int or context["me_window_minutes"] < 0 or context["me_window_minutes"] > 120:
        raise RRException("config_invalid", "context.me_window_minutes must be an integer between 0 and 120")
    context["selection_mode"] = os.environ.get("RR_SELECTION_MODE", context.get("selection_mode", "me_context"))
    if context["selection_mode"] not in ("me_context", "all"):
        raise RRException("config_invalid", "context.selection_mode must be me_context or all")
    if not isinstance(asr, dict) or asr.get("language") != "zh" or asr.get("allowed_languages") != ["zh"]:
        raise RRException("config_invalid", "SenseVoice must use single zh language mode")
    return config


def data_root(config: dict[str, Any]) -> Path:
    return Path(config["data_root"])


def init_dirs(root: Path) -> None:
    for rel in ("raw", "raw/.staging", "work", "output", "output/.staging", "voiceprints/me", "state", "locks", "logs"):
        (root / rel).mkdir(parents=True, exist_ok=True, mode=0o750)


class State:
    def __init__(self, root: Path):
        init_dirs(root)
        self.conn = sqlite3.connect(root / "state/state.db")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS recordings (
          recording_id TEXT PRIMARY KEY,
          source_provider TEXT NOT NULL,
          created_at TEXT,
          start_at TEXT NOT NULL,
          duration_ms INTEGER NOT NULL,
          local_date TEXT NOT NULL,
          serial_number TEXT,
          remote_state TEXT NOT NULL,
          local_path TEXT,
          file_size INTEGER,
          sha256 TEXT,
          media_format TEXT,
          remote_etag TEXT,
          remote_size INTEGER,
          first_seen_at TEXT NOT NULL,
          downloaded_at TEXT,
          updated_at TEXT NOT NULL,
          last_error TEXT
        );
        CREATE TABLE IF NOT EXISTS stage_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          scope_type TEXT NOT NULL,
          scope_id TEXT NOT NULL,
          stage TEXT NOT NULL,
          status TEXT NOT NULL,
          input_hash TEXT NOT NULL,
          config_hash TEXT NOT NULL,
          attempts INTEGER NOT NULL DEFAULT 1,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          error_code TEXT,
          error_summary TEXT,
          artifact_path TEXT,
          artifact_hash TEXT,
          metrics_json TEXT,
          UNIQUE(scope_type, scope_id, stage, input_hash, config_hash)
        );
        """)

    def close(self) -> None:
        self.conn.close()

    def upsert_recording(self, row: dict[str, Any]) -> None:
        existing = self.get_recording(row["recording_id"])
        seen = existing["first_seen_at"] if existing else now_iso()
        values = {**row, "first_seen_at": seen, "updated_at": now_iso()}
        columns = ["recording_id", "source_provider", "created_at", "start_at", "duration_ms", "local_date", "serial_number", "remote_state", "local_path", "file_size", "sha256", "media_format", "remote_etag", "remote_size", "first_seen_at", "downloaded_at", "updated_at", "last_error"]
        with self.conn:
            self.conn.execute(f"INSERT INTO recordings ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(recording_id) DO UPDATE SET " + ",".join(f"{column}=excluded.{column}" for column in columns if column not in ("recording_id", "first_seen_at")), [values.get(column) for column in columns])

    def get_recording(self, recording_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM recordings WHERE recording_id=?", (recording_id,)).fetchone()

    def recordings_for_date(self, date: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM recordings WHERE local_date=? ORDER BY start_at, recording_id", (date,)).fetchall()

    def stage_done(self, scope_type: str, scope_id: str, stage: str, input_hash: str, config_hash: str) -> bool:
        row = self.conn.execute("SELECT * FROM stage_runs WHERE scope_type=? AND scope_id=? AND stage=? AND input_hash=? AND config_hash=?", (scope_type, scope_id, stage, input_hash, config_hash)).fetchone()
        if not row or row["status"] != "done" or not row["artifact_path"]:
            return False
        artifact = Path(row["artifact_path"])
        return artifact.is_file() and sha256_file(artifact) == row["artifact_hash"]

    def begin_stage(self, scope_type: str, scope_id: str, stage: str, input_hash: str, config_hash: str) -> None:
        with self.conn:
            self.conn.execute("""INSERT INTO stage_runs(scope_type,scope_id,stage,status,input_hash,config_hash,started_at)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(scope_type,scope_id,stage,input_hash,config_hash)
              DO UPDATE SET status='running',attempts=attempts+1,started_at=excluded.started_at,error_code=NULL,error_summary=NULL""",
              (scope_type, scope_id, stage, "running", input_hash, config_hash, now_iso()))

    def finish_stage(self, scope_type: str, scope_id: str, stage: str, input_hash: str, config_hash: str, artifact: Path, metrics: dict[str, Any] | None = None) -> None:
        with self.conn:
            self.conn.execute("""UPDATE stage_runs SET status='done',finished_at=?,artifact_path=?,artifact_hash=?,metrics_json=?
              WHERE scope_type=? AND scope_id=? AND stage=? AND input_hash=? AND config_hash=?""",
              (now_iso(), str(artifact), sha256_file(artifact), json.dumps(metrics or {}), scope_type, scope_id, stage, input_hash, config_hash))

    def fail_stage(self, scope_type: str, scope_id: str, stage: str, input_hash: str, config_hash: str, error: RRException) -> None:
        with self.conn:
            self.conn.execute("""UPDATE stage_runs SET status='failed',finished_at=?,error_code=?,error_summary=?
              WHERE scope_type=? AND scope_id=? AND stage=? AND input_hash=? AND config_hash=?""",
              (now_iso(), error.code, str(error)[:500], scope_type, scope_id, stage, input_hash, config_hash))

    def wait_stage(self, scope_type: str, scope_id: str, stage: str, input_hash: str, config_hash: str, reason: str) -> None:
        self.begin_stage(scope_type, scope_id, stage, input_hash, config_hash)
        with self.conn:
            self.conn.execute("""UPDATE stage_runs SET status='waiting',finished_at=?,error_code=?
              WHERE scope_type=? AND scope_id=? AND stage=? AND input_hash=? AND config_hash=?""",
              (now_iso(), reason, scope_type, scope_id, stage, input_hash, config_hash))
