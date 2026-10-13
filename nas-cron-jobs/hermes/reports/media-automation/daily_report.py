#!/usr/bin/env python3
"""Prepare changes since the last delivered report; source stores stay read-only."""

from __future__ import annotations

import json
import hashlib
import os
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo("Asia/Taipei")
MOVIEPILOT_DB = Path("/vol2/1000/Docker/moviepilot/config/user.db")
THEME_WORKER_DB = Path("/vol2/1000/Docker/emby-theme-worker/data/worker.db")
HERMES_ENV = Path("/home/hermes/.hermes/.env")
MOVIEPILOT_API_BASE = "http://127.0.0.1:28300/api/v1"
MOVIEPILOT_TOKEN_ENV_KEY = "AUXILIARY_MEDIA_AUTOMATION_API_KEY"
MOVIEPILOT_PLUGINS = ("MediaArchive", "DiscRemux")
CHECKPOINT = Path("/home/hermes/.hermes/profiles/lingjun/cron/report-state/media-automation.json")

TASK_STAGE_LABELS = {
    "ANALYZING": "分析中",
    "CHECKING": "检查中",
    "CLEANING": "清理中",
    "CLOUD_VERIFY": "云端校验中",
    "CONVERTING": "转换中",
    "DONE": "已完成",
    "FAILED": "失败",
    "MIGRATING": "迁移中",
    "MANUAL": "需要人工处理",
    "PREPARING": "准备中",
    "PREVIEW": "预检中",
    "SEED_WAIT": "等待做种",
    "STRM_VERIFY": "STRM 校验中",
    "UPLOADING": "上传中",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep the MoviePilot credential on the configured API without redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class MoviePilotAPIError(RuntimeError):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def moviepilot_api_base() -> str:
    path = Path(os.environ.get("HERMES_CRON_CONFIG", "/home/yuwk/cron/env/hermes.local.json"))
    try:
        config = json.loads(path.read_text()) if path.exists() else {}
        base = str(config.get("moviepilot_api_base", MOVIEPILOT_API_BASE)).rstrip("/")
        from urllib.parse import urlsplit
        import ipaddress
        url = urlsplit(base)
        address = ipaddress.ip_address(url.hostname)
        if (url.scheme not in {"http", "https"} or url.username is not None
                or url.password is not None or url.query or url.fragment
                or url.path != "/api/v1" or not (address.is_private or address.is_loopback)):
            raise ValueError()
        return base
    except (OSError, ValueError, TypeError, AttributeError):
        raise MoviePilotAPIError("MoviePilot 本机接口配置无效或不可读") from None


def moviepilot_api_token() -> str:
    """Read the shared MoviePilot credential without logging or exporting it."""
    try:
        lines = HERMES_ENV.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise MoviePilotAPIError(
            f"无法读取 Hermes 根凭据文件（{type(exc).__name__}）"
        ) from None

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, separator, value = line.partition("=")
        if not separator or key.strip() != MOVIEPILOT_TOKEN_ENV_KEY:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        if not value:
            break
        if not value.isascii() or any(ord(char) < 33 or ord(char) == 127 for char in value):
            raise MoviePilotAPIError("Hermes 中的 MoviePilot 凭据格式无效")
        return value
    raise MoviePilotAPIError(
        f"Hermes 根凭据中缺少 {MOVIEPILOT_TOKEN_ENV_KEY}"
    )


def _job_records(value: object) -> list[dict] | None:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if "stage" in value or "id" in value:
            return [value]
        return [item for item in value.values() if isinstance(item, dict)]
    return None


def moviepilot_job_snapshots() -> tuple[dict[str, list[dict] | None], list[str], str]:
    """Read both plugin /jobs APIs with the API_TOKEN in X-API-KEY only."""
    snapshots: dict[str, list[dict] | None] = {}
    issues: list[str] = []
    try:
        token = moviepilot_api_token()
        base = moviepilot_api_base()
    except MoviePilotAPIError as exc:
        detail = exc.detail
        return {plugin: None for plugin in MOVIEPILOT_PLUGINS}, [detail], ""

    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect()
    )
    for plugin in MOVIEPILOT_PLUGINS:
        route = f"/plugin/{plugin}/jobs"
        request = urllib.request.Request(
            base + route,
            headers={"X-API-KEY": token, "Accept": "application/json"},
            method="GET",
        )
        try:
            with opener.open(request, timeout=15) as response:
                payload = json.loads(response.read(5 * 1024 * 1024 + 1).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            snapshots[plugin] = None
            issues.append(f"{plugin} /jobs 查询失败（HTTP {exc.code}）")
            continue
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            snapshots[plugin] = None
            issues.append(
                f"{plugin} /jobs 请求失败（{type(exc).__name__}）"
            )
            continue
        except (UnicodeDecodeError, json.JSONDecodeError):
            snapshots[plugin] = None
            issues.append(f"{plugin} /jobs 返回内容不是有效 JSON")
            continue

        if not isinstance(payload, dict):
            snapshots[plugin] = None
            issues.append(f"{plugin} /jobs 返回结构无效，缺少 jobs 对象")
            continue
        if payload.get("error") or payload.get("scan_error"):
            snapshots[plugin] = None
            issues.append(f"{plugin}：" + _safe_api_text(payload.get("error") or payload["scan_error"], token))
            continue

        records = _job_records(payload.get("jobs"))
        if records is None:
            snapshots[plugin] = None
            issues.append(f"{plugin} /jobs 响应缺少可读取的 jobs 数据")
        else:
            snapshots[plugin] = records
    return snapshots, issues, token


def _safe_api_text(value: object, token: str, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if token:
        text = text.replace(token, "[凭据已隐藏]")
    return text[:limit]


def _api_title(job: dict, plugin: str, token: str) -> str:
    candidates: list[object] = []
    if plugin == "MediaArchive":
        unit = job.get("unit")
        if isinstance(unit, dict):
            candidates.extend((unit.get("title"), unit.get("name")))
        candidates.extend((job.get("title"), job.get("name")))
    else:
        request = job.get("request")
        if isinstance(request, dict):
            candidates.extend((request.get("title"), request.get("name")))
        candidates.extend((job.get("title"), job.get("name")))
        for title in job.get("titles", []) if isinstance(job.get("titles"), list) else []:
            if isinstance(title, dict):
                candidates.extend((title.get("name"), title.get("output_name")))
    for candidate in candidates:
        cleaned = _safe_api_text(candidate, token, 120)
        if cleaned:
            return cleaned
    return ""


def _collection_size(value: object) -> int | None:
    if isinstance(value, (list, dict)):
        return len(value)
    return None


def plugin_snapshot(plugin: str, jobs: list[dict], token: str) -> dict[str, dict]:
    result = {}
    for job in jobs:
        identity = job.get("id") or (job.get("unit") or {}).get("key")
        if not identity:
            identity = hashlib.sha256(json.dumps(job.get("request") or {}, sort_keys=True).encode()).hexdigest()
        cleanup = job.get("cleanup") or {}
        result[str(identity)] = {
            "title": _api_title(job, plugin, token),
            "stage": _safe_api_text(job.get("stage") or "状态未知", token, 60),
            "reason": _safe_api_text(job.get("reason"), token),
            "cleanup": cleanup.get("complete") if isinstance(cleanup, dict) else None,
            "assets": _collection_size(job.get("assets")),
            "outputs": _collection_size(job.get("outputs")),
        }
    return result


def plugin_changes(plugin: str, previous: dict | None, current: dict) -> list[str]:
    # The APIs have no event time. An initial snapshot is a baseline, not new work.
    if previous is None:
        return []
    lines = []
    for key, job in current.items():
        old = previous.get(key)
        if old == job:
            continue
        stage = TASK_STAGE_LABELS.get(job["stage"], job["stage"])
        if old is None:
            detail = "新增，" + stage
        elif old["stage"] != job["stage"]:
            detail = TASK_STAGE_LABELS.get(old["stage"], old["stage"]) + " → " + stage
        else:
            detail = stage
        if job["reason"]:
            detail += "；" + job["reason"]
        if old is not None and job["cleanup"] is True and old.get("cleanup") is not True:
            detail += "；清理完成"
        if old is not None and job["outputs"] is not None and old.get("outputs") != job["outputs"]:
            detail += f"；产物 {job['outputs']} 项"
        lines.append(f"- {plugin} {wrapped_title(job['title'])}：{detail}")
    for key, job in previous.items():
        if key not in current:
            lines.append(f"- {plugin} {wrapped_title(job['title'])}：任务记录移除")
    return lines


def parse_time(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            parsed = datetime.fromtimestamp(float(value), TIMEZONE)
        else:
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=TIMEZONE)
            else:
                parsed = parsed.astimezone(TIMEZONE)
        return parsed
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def open_readonly(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    if immutable:
        uri += "&immutable=1"
    connection = sqlite3.connect(uri, uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def moviepilot_rows() -> tuple[list[dict], list[dict]]:
    with closing(open_readonly(MOVIEPILOT_DB)) as connection:
        downloads = [
            dict(row) for row in connection.execute(
                "SELECT title, torrent_name, date, download_hash, username "
                "FROM downloadhistory"
            )
        ]
        plugin_rows = connection.execute(
            "SELECT value FROM plugindata "
            "WHERE plugin_id = ? AND key = ?",
            ("FilmWatchlist", "records"),
        ).fetchall()

    records: list[dict] = []
    for row in plugin_rows:
        try:
            payload = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("FilmWatchlist records JSON is invalid") from exc
        if isinstance(payload, dict):
            if "title" in payload or "status" in payload:
                candidates = [payload]
            else:
                candidates = list(payload.values())
        elif isinstance(payload, list):
            candidates = payload
        else:
            candidates = []
        records.extend(dict(item) for item in candidates if isinstance(item, dict))
    return downloads, records


def theme_worker_rows() -> list[dict]:
    for attempt in range(3):
        try:
            return _theme_worker_rows_once()
        except (RuntimeError, sqlite3.OperationalError):
            if attempt == 2:
                raise
            time.sleep(0.2)


def _theme_worker_rows_once() -> list[dict]:
    # Use SQLite's read-only WAL support when its worker-created sidecars are
    # present. When the worker has checkpointed and removed them, use immutable
    # mode because normal read-only SQLite tries to create a missing SHM file.
    wal = Path(str(THEME_WORKER_DB) + "-wal")
    shm = Path(str(THEME_WORKER_DB) + "-shm")
    journal = Path(str(THEME_WORKER_DB) + "-journal")

    def signature() -> tuple[int, int, int, bytes]:
        stat = THEME_WORKER_DB.stat()
        with THEME_WORKER_DB.open("rb") as stream:
            header = stream.read(28)
        if not header.startswith(b"SQLite format 3\x00"):
            raise ValueError("Theme worker database header is invalid")
        if header[18:20] != b"\x02\x02":
            raise ValueError("Theme worker database journal mode changed")
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, header[24:28]

    def file_signature(path: Path) -> tuple[int, int, int] | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return stat.st_ino, stat.st_size, stat.st_mtime_ns

    if file_signature(journal) is not None:
        raise RuntimeError("Theme worker database has an active rollback journal")
    before = signature()
    before_wal = file_signature(wal)
    if before_wal is not None:
        if file_signature(shm) is None:
            raise RuntimeError("Theme worker WAL is present without its shared-memory file")
        immutable = False
    else:
        immutable = True
    with closing(open_readonly(THEME_WORKER_DB, immutable=immutable)) as connection:
        rows = [
            dict(row) for row in connection.execute(
                "SELECT emby_id, name, status, source_provider, updated_at FROM items"
            )
        ]
    if (
        signature() != before
        or file_signature(wal) != before_wal
        or file_signature(journal) is not None
    ):
        raise RuntimeError("Theme worker database changed during the read")
    return rows


def wrapped_title(value: object) -> str:
    title = str(value or "").strip()
    if title.startswith("《") and title.endswith("》"):
        return title
    return f"《{title or '未命名影视'}》"


def recent_rows(
    rows: list[dict], time_field: str, cutoff: datetime, now: datetime
) -> tuple[list[dict], int]:
    recent: list[dict] = []
    invalid = 0
    for row in rows:
        value = row.get(time_field)
        parsed = parse_time(value)
        if parsed is None:
            raw_date = str(value or "").strip()[:10]
            if cutoff.date().isoformat() <= raw_date <= now.date().isoformat():
                invalid += 1
            continue
        if cutoff < parsed <= now:
            row["_parsed_time"] = parsed
            recent.append(row)
    return recent, invalid


def watchlist_records(records: list[dict]) -> dict[str, dict]:
    by_hash: dict[str, dict] = {}
    for record in records:
        key = str(record.get("download_hash") or "").strip()
        if not key:
            continue
        current = by_hash.get(key)
        updated = parse_time(record.get("updated_at"))
        previous = parse_time(current.get("updated_at")) if current else None
        if current is None or (updated and (previous is None or updated > previous)):
            by_hash[key] = record
    return by_hash


def changed_rows(rows, recent, previous, time_field, now, fields, identity_fields, *, initial_events=False):
    fingerprints = {}
    selected = []
    for row in rows:
        timestamp = parse_time(row.get(time_field))
        if timestamp is None or timestamp > now:
            continue
        identity = [row.get(field) for field in identity_fields]
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        detail = {field: row.get(field) for field in fields}
        fingerprint = hashlib.sha256(json.dumps(detail, sort_keys=True).encode()).hexdigest()
        fingerprints[key] = fingerprint
        if row in recent and ((previous is None and initial_events)
                              or (previous is not None and previous.get(key) != fingerprint)):
            selected.append(row)
    return selected, fingerprints


def load_checkpoint(path: Path = CHECKPOINT) -> dict | None:
    try:
        with path.open("rb") as stream:
            raw = stream.read(5 * 1024 * 1024 + 1)
    except FileNotFoundError:
        return None
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("media checkpoint exceeds read limit")
    value = json.loads(raw)
    if (not isinstance(value, dict) or value.get("schema") != 1
            or not isinstance(value.get("plugins"), dict) or parse_time(value.get("checked_at")) is None):
        raise ValueError("invalid media checkpoint")
    return value


def save_checkpoint(value: dict, path: Path = CHECKPOINT):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".media-report-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def prepare_report(now: datetime, previous: dict | None = None) -> tuple[str, int, dict]:
    cutoff = parse_time(previous["checked_at"]) if previous else now - timedelta(hours=24)
    if cutoff > now:
        raise ValueError("media checkpoint is in the future")
    downloads, records = moviepilot_rows()
    theme_items = theme_worker_rows()
    plugin_jobs, plugin_issues, api_token = moviepilot_job_snapshots()
    recent_downloads, invalid_downloads = recent_rows(downloads, "date", cutoff, now)
    recent_records, invalid_records = recent_rows(records, "updated_at", cutoff, now)
    recent_theme, invalid_theme = recent_rows(theme_items, "updated_at", cutoff, now)
    old_records = previous.get("records", {}) if previous else {}
    recent_downloads, download_baseline = changed_rows(downloads, recent_downloads, old_records.get("downloads"),
        "date", now, ("title", "download_hash", "date"), ("download_hash", "title", "date"), initial_events=True)
    recent_records, watchlist_baseline = changed_rows(records, recent_records, old_records.get("watchlist"),
        "updated_at", now, ("title", "status", "download_hash"), ("film_id", "title"))
    recent_theme, theme_baseline = changed_rows(theme_items, recent_theme, old_records.get("themes"),
        "updated_at", now, ("name", "status", "source_provider"), ("emby_id", "name"))
    status_by_hash = watchlist_records(recent_records)

    lines = []
    linked_hashes: set[str] = set()
    for row in sorted(recent_downloads, key=lambda item: item["_parsed_time"]):
        title = wrapped_title(row.get("title"))
        download_hash = str(row.get("download_hash") or "").strip()
        record = status_by_hash.get(download_hash)
        detail = "已提交" + ("；" + str(record.get("status") or "状态未知") if record else "")
        lines.append(f"- 下载 {title}：{detail}")
        if record:
            linked_hashes.add(download_hash)

    independent_records = [
        row for row in recent_records
        if str(row.get("download_hash") or "").strip() not in linked_hashes
    ]
    for row in sorted(independent_records, key=lambda item: item["_parsed_time"]):
        status = str(row.get("status") or "状态未知").strip()
        lines.append(f"- 片单 {wrapped_title(row.get('title'))}：{status}")

    for row in sorted(recent_theme, key=lambda item: item["_parsed_time"]):
        status = str(row.get("status") or "状态未知").strip()
        lines.append(f"- 主题曲 {wrapped_title(row.get('name'))}：{status}")

    next_plugins = dict(previous["plugins"]) if previous else {}
    for plugin in MOVIEPILOT_PLUGINS:
        jobs = plugin_jobs.get(plugin)
        if jobs is not None:
            current = plugin_snapshot(plugin, jobs, api_token)
            lines.extend(plugin_changes(plugin, next_plugins.get(plugin), current))
            next_plugins[plugin] = current
    old_issues = previous.get("issues", []) if previous else []
    lines.extend("- 数据源：" + issue for issue in plugin_issues if issue not in old_issues)

    invalid = invalid_downloads + invalid_records + invalid_theme
    if invalid:
        lines.append(f"- 时间字段：{invalid} 条记录无法识别变更时间")
    report = "\n".join([f"**影视变更 · {now:%m-%d}**", *lines]) if lines else ""
    checkpoint = {"schema": 1, "checked_at": now.isoformat(), "plugins": next_plugins, "issues": plugin_issues,
                  "records": {"downloads": download_baseline, "watchlist": watchlist_baseline, "themes": theme_baseline}}
    return report, invalid + len(plugin_issues), checkpoint


def build_report(now: datetime) -> tuple[str, int]:
    report, invalid, _checkpoint = prepare_report(now, load_checkpoint())
    return report, invalid


def main() -> int:
    now = datetime.now(TIMEZONE)
    try:
        report, _invalid = build_report(now)
    except (OSError, sqlite3.Error, ValueError, RuntimeError, TypeError, KeyError):
        print("- 影视日报：无法读取变更记录")
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
