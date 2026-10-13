#!/usr/bin/env python3
"""Read MoviePilot databases, plugin job APIs, and theme-worker data."""

from __future__ import annotations

import json
import os
import sqlite3
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
MAX_PLUGIN_JOB_DETAILS = 30

TASK_STAGE_LABELS = {
    "ANALYZING": "分析中",
    "CHECKING": "检查中",
    "CLEANING": "清理中",
    "CLOUD_VERIFY": "云端校验中",
    "CONVERTING": "转换中",
    "DONE": "已完成",
    "FAILED": "失败",
    "MIGRATING": "迁移中",
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
        if payload.get("busy") is True:
            issues.append(f"{plugin} 当前 busy，任务快照可能不完整")
        if payload.get("error"):
            issues.append(f"{plugin} 响应包含 error，任务快照可能不完整")
        if payload.get("scan_error"):
            issues.append(f"{plugin} 扫描发生异常，任务快照可能不完整")

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


def _plugin_job_lines(plugin: str, jobs: list[dict], token: str) -> list[str]:
    lines = [f"{plugin} 任务当前状态（{len(jobs)}）"]
    if not jobs:
        lines.append("- 当前无任务记录")
        return lines

    stage_counts: dict[str, int] = {}
    for job in jobs:
        stage = _safe_api_text(job.get("stage") or "状态未知", token, 60)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    summaries = [
        f"{TASK_STAGE_LABELS.get(stage, stage)} ×{count}"
        for stage, count in sorted(stage_counts.items())
    ]
    lines.append("阶段汇总：" + "；".join(summaries))

    shown = jobs[:MAX_PLUGIN_JOB_DETAILS]
    for job in shown:
        title = _api_title(job, plugin, token)
        media = wrapped_title(title or "媒体名称缺失")
        stage = _safe_api_text(job.get("stage") or "状态未知", token, 60)
        label = TASK_STAGE_LABELS.get(stage, "状态未知")
        detail = f"- {media}：{label}（{stage}）"
        if not title:
            detail += "；任务记录未提供影视名称"

        if plugin == "MediaArchive":
            cleanup = job.get("cleanup")
            if isinstance(cleanup, dict) and isinstance(cleanup.get("complete"), bool):
                detail += "；清理已完成" if cleanup["complete"] else "；清理未完成"
            asset_count = _collection_size(job.get("assets"))
            if asset_count is not None:
                detail += f"；资产 {asset_count} 项"
        else:
            output_count = _collection_size(job.get("outputs"))
            if output_count is not None:
                detail += f"；产物 {output_count} 项"
            title_count = _collection_size(job.get("titles"))
            if title_count is not None:
                detail += f"；解析条目 {title_count} 项"

        reason = _safe_api_text(job.get("reason"), token)
        if reason:
            detail += f"；说明：{reason}"
        elif stage not in {"DONE", "状态未知"} and not title:
            detail += "；异常原因和影视名称均未提供"
        elif stage not in {"DONE", "状态未知"}:
            detail += "；记录未提供阶段说明"
        lines.append(detail)

    if len(jobs) > len(shown):
        lines.append(
            f"数据不足：另有 {len(jobs) - len(shown)} 条任务未展开；"
            "接口记录没有更新时间，无法识别过去24小时内变更的记录。"
        )
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
                "SELECT name, status, source_provider, updated_at FROM items"
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


def display_time(value: datetime | None) -> str:
    return value.strftime("%m-%d %H:%M") if value else "时间未知"


def recent_rows(
    rows: list[dict], time_field: str, cutoff: datetime
) -> tuple[list[dict], int]:
    recent: list[dict] = []
    invalid = 0
    for row in rows:
        value = row.get(time_field)
        parsed = parse_time(value)
        if parsed is None:
            raw_date = str(value or "").strip()[:10]
            if raw_date >= cutoff.date().isoformat():
                invalid += 1
            continue
        if parsed >= cutoff:
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


def build_report(now: datetime) -> tuple[str, int]:
    cutoff = now - timedelta(hours=24)
    downloads, records = moviepilot_rows()
    theme_items = theme_worker_rows()
    plugin_jobs, plugin_issues, api_token = moviepilot_job_snapshots()
    recent_downloads, invalid_downloads = recent_rows(downloads, "date", cutoff)
    recent_records, invalid_records = recent_rows(records, "updated_at", cutoff)
    recent_theme, invalid_theme = recent_rows(theme_items, "updated_at", cutoff)
    status_by_hash = watchlist_records(records)

    lines = [f"影视自动化日报 {now:%Y-%m-%d %H:%M}（过去24小时）"]
    lines.append(f"下载提交（{len(recent_downloads)}）")
    linked_hashes: set[str] = set()
    for row in sorted(recent_downloads, key=lambda item: item["_parsed_time"]):
        title = wrapped_title(row.get("title"))
        source = str(row.get("username") or "来源未知").strip()
        download_hash = str(row.get("download_hash") or "").strip()
        record = status_by_hash.get(download_hash) if source == "FilmWatchlist" else None
        lines.append(f"- {title}：提交时间 {display_time(row['_parsed_time'])}；来源 {source}")
        if source == "FilmWatchlist":
            if record is not None:
                linked_hashes.add(download_hash)
                status = str(record.get("status") or "状态未知").strip()
                lines.append(f"  片单处理状态：{status}")
            else:
                lines.append("  片单处理状态：未找到匹配记录")
        release = str(row.get("torrent_name") or "").strip()
        if release:
            lines.append(f"  下载格式：{release}")

    independent_records = [
        row for row in recent_records
        if str(row.get("download_hash") or "").strip() not in linked_hashes
    ]
    lines.append(f"片单状态更新（{len(independent_records)}）")
    for row in sorted(independent_records, key=lambda item: item["_parsed_time"]):
        status = str(row.get("status") or "状态未知").strip()
        lines.append(
            f"- {wrapped_title(row.get('title'))}：片单处理状态 {status}；"
            f"更新时间 {display_time(row['_parsed_time'])}"
        )
        release = str(row.get("torrent_title") or "").strip()
        if release:
            lines.append(f"  下载格式：{release}")

    lines.append(f"主题曲任务（{len(recent_theme)}）")
    for row in sorted(recent_theme, key=lambda item: item["_parsed_time"]):
        status = str(row.get("status") or "状态未知").strip()
        provider = str(row.get("source_provider") or "来源未知").strip()
        lines.append(
            f"- {wrapped_title(row.get('name'))}：{status}；来源 {provider}；"
            f"更新时间 {display_time(row['_parsed_time'])}"
        )

    lines.append(
        "MoviePilot 插件任务当前快照（接口未提供任务更新时间，"
        "不代表过去24小时新增或变更）"
    )
    for plugin in MOVIEPILOT_PLUGINS:
        jobs = plugin_jobs.get(plugin)
        if jobs is None:
            lines.append(f"{plugin}：当前状态不可用")
        else:
            lines.extend(_plugin_job_lines(plugin, jobs, api_token))
    if plugin_issues:
        lines.append("任务数据提示：" + "；".join(plugin_issues))

    invalid = invalid_downloads + invalid_records + invalid_theme
    if invalid:
        lines.append(f"数据提示：{invalid} 条记录的时间字段无法解析，报告可能不完整。")
    if (
        not recent_downloads and not independent_records and not recent_theme
        and not invalid and not any(plugin_jobs.get(plugin) for plugin in MOVIEPILOT_PLUGINS)
        and not plugin_issues
    ):
        lines.append("过去24小时无新增下载、片单状态更新或主题曲处理记录。")
    return "\n".join(lines), invalid + len(plugin_issues)


def main() -> int:
    now = datetime.now(TIMEZONE)
    try:
        report, _invalid = build_report(now)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(
            f"影视自动化日报失败：只读数据库查询异常"
            f"（{type(exc).__name__}: {str(exc).splitlines()[0][:220]}）"
        )
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
