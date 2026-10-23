#!/usr/bin/env python3
"""只读采集 Google Calendar 与当天完成的 Tasks，写入最小日报摘要。"""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


APP_ROOT = Path(os.environ.get("REVIEW_APP_ROOT", str(Path(__file__).resolve().parents[2])))

from review.config import load_config  # noqa: E402


class GoogleReadError(RuntimeError):
    """表示 Google 只读采集失败，消息不得包含凭据或响应正文。"""


class GoogleReadClient:
    """用受限凭据文件刷新短期 access token，并只执行 GET。"""

    def __init__(self, credential_file: Path) -> None:
        """读取 OAuth 配置；凭据内容仅驻留内存。"""

        mode = credential_file.stat().st_mode & 0o777
        if mode & 0o077:
            raise GoogleReadError("Google 凭据文件权限必须为 0600")
        try:
            values = json.loads(credential_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GoogleReadError("Google 凭据文件无法读取") from exc
        required = ("client_id", "client_secret", "refresh_token", "token_uri")
        if not isinstance(values, dict) or any(not values.get(key) for key in required):
            raise GoogleReadError("Google 凭据缺少 OAuth 刷新字段")
        self.values = values
        self.access_token = self._refresh()

    def _refresh(self) -> str:
        """刷新 access token；失败只返回 HTTP 类别，不回显服务响应。"""

        payload = urlencode(
            {
                "client_id": self.values["client_id"],
                "client_secret": self.values["client_secret"],
                "refresh_token": self.values["refresh_token"],
                "grant_type": "refresh_token",
            }
        ).encode("utf-8")
        request = Request(str(self.values["token_uri"]), data=payload, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urlopen(request, timeout=20) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            # 只识别 OAuth 标准错误码，不把响应正文或凭据写入日志。
            try:
                oauth_error = json.loads(exc.read().decode("utf-8", "replace")).get("error")
            except (AttributeError, json.JSONDecodeError):
                oauth_error = None
            if oauth_error == "invalid_grant":
                raise GoogleReadError("Google OAuth 凭据已失效，需要重新授权") from exc
            raise GoogleReadError(f"Google OAuth 刷新失败：HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GoogleReadError(f"Google OAuth 刷新失败：{type(exc).__name__}") from exc
        token = result.get("access_token") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise GoogleReadError("Google OAuth 刷新未返回 access token")
        return token

    def get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """执行一个只读 Google REST 请求并返回 JSON 对象。"""

        request = Request(f"{url}?{urlencode(params, doseq=True)}", method="GET")
        request.add_header("Authorization", f"Bearer {self.access_token}")
        request.add_header("Accept", "application/json")
        try:
            with urlopen(request, timeout=30) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            raise GoogleReadError(f"Google API 读取失败：HTTP {exc.code}") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise GoogleReadError(f"Google API 读取失败：{type(exc).__name__}") from exc
        if not isinstance(result, dict):
            raise GoogleReadError("Google API 返回结构不是对象")
        return result


def _load_proxy_environment(path: Path) -> None:
    """从 Hermes 私有 ENV 中只读取代理变量，避免 cron 清理环境后失去外网。"""

    mode = path.stat().st_mode & 0o777
    if mode & 0o007:
        raise GoogleReadError("Hermes 代理 ENV 不得允许其他用户读取")
    allowed = {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise GoogleReadError("Hermes 代理 ENV 无法读取") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in allowed or key in os.environ:
            continue
        # 只做 dotenv 字面量读取，不执行 shell 展开或命令替换。
        parsed = value.strip().strip('"').strip("'")
        if parsed and "\x00" not in parsed:
            os.environ[key] = parsed


def _parser() -> argparse.ArgumentParser:
    """构建支持历史窗口回放的只读参数。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD，默认业务时区今天")
    return parser


def _window(config: Any, value: str | None) -> tuple[datetime, datetime]:
    """构造业务日自然窗口，Google 输入可供 21:30 日报读取。"""

    day = date.fromisoformat(value) if value else datetime.now(config.timezone).date()
    return datetime.combine(day, time.min, config.timezone), datetime.combine(day, time.max, config.timezone)


def _rfc3339(value: datetime) -> str:
    """把带时区时间转换为 Google API 接受的 UTC RFC3339。"""

    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_google_time(value: Any, zone: Any) -> datetime | None:
    """解析 Calendar 的 dateTime 或全天 date 字段。"""

    if not isinstance(value, dict):
        return None
    raw = value.get("dateTime")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
        except ValueError:
            return None
    raw_date = value.get("date")
    if isinstance(raw_date, str):
        try:
            return datetime.combine(date.fromisoformat(raw_date), time.min, zone)
        except ValueError:
            return None
    return None


def _calendar_period(start: datetime, end: datetime, all_day: bool, zone: Any) -> str:
    """生成不含描述和参与人的紧凑时间范围。"""

    if all_day:
        return "全天"
    local_start = start.astimezone(zone)
    local_end = end.astimezone(zone)
    if local_start.date() == local_end.date():
        return f"{local_start:%H:%M}–{local_end:%H:%M}"
    return f"{local_start:%m-%d %H:%M}–{local_end:%m-%d %H:%M}"


def _calendar(client: GoogleReadClient, start: datetime, end: datetime, maximum: int, zone: Any) -> list[dict[str, Any]]:
    """读取窗口内未取消事件，只保留 ID、标题、时间和状态。"""

    result: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "timeMin": _rfc3339(start),
            "timeMax": _rfc3339(end),
            "singleEvents": "true",
            "orderBy": "startTime",
            "showDeleted": "false",
            "maxResults": maximum,
        }
        if page_token:
            params["pageToken"] = page_token
        payload = client.get("https://www.googleapis.com/calendar/v3/calendars/primary/events", params)
        for item in payload.get("items", []):
            if not isinstance(item, dict) or item.get("status") == "cancelled":
                continue
            event_start = _parse_google_time(item.get("start"), zone)
            event_end = _parse_google_time(item.get("end"), zone)
            event_id = str(item.get("id") or "").strip()
            summary = str(item.get("summary") or "").strip()
            if event_start is None or event_end is None or not event_id or not summary:
                continue
            all_day = isinstance(item.get("start"), dict) and bool(item["start"].get("date"))
            result.append(
                {
                    "id": event_id,
                    "summary": summary,
                    "status": str(item.get("status") or "confirmed"),
                    "occurred_at": event_start.isoformat(),
                    "period": _calendar_period(event_start, event_end, all_day, zone),
                }
            )
        page_token = str(payload.get("nextPageToken") or "") or None
        if not page_token:
            return result


def _tasks(client: GoogleReadClient, start: datetime, end: datetime, maximum: int) -> list[dict[str, Any]]:
    """遍历任务清单，只保留窗口内真实 completed 项。"""

    tasklists: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"maxResults": maximum}
        if page_token:
            params["pageToken"] = page_token
        payload = client.get("https://tasks.googleapis.com/tasks/v1/users/@me/lists", params)
        tasklists.extend(item for item in payload.get("items", []) if isinstance(item, dict))
        page_token = str(payload.get("nextPageToken") or "") or None
        if not page_token:
            break

    result: list[dict[str, Any]] = []
    for tasklist in tasklists:
        tasklist_id = str(tasklist.get("id") or "").strip()
        if not tasklist_id:
            continue
        page_token = None
        while True:
            params = {
                "showCompleted": "true",
                "showHidden": "true",
                "completedMin": _rfc3339(start),
                "completedMax": _rfc3339(end),
                "maxResults": maximum,
            }
            if page_token:
                params["pageToken"] = page_token
            payload = client.get(f"https://tasks.googleapis.com/tasks/v1/lists/{quote(tasklist_id, safe='')}/tasks", params)
            for item in payload.get("items", []):
                if not isinstance(item, dict) or item.get("status") != "completed":
                    continue
                task_id = str(item.get("id") or "").strip()
                title = str(item.get("title") or "").strip()
                completed = str(item.get("completed") or "").strip()
                if task_id and title and completed:
                    result.append(
                        {
                            "id": task_id,
                            "tasklist_id": tasklist_id,
                            "title": title,
                            "status": "completed",
                            "completed_at": completed,
                        }
                    )
            page_token = str(payload.get("nextPageToken") or "") or None
            if not page_token:
                break
    return result


def collect(value: str | None = None) -> dict[str, Any]:
    """采集 Google 最小摘要；单服务失败不阻断另一服务。"""

    config = load_config(APP_ROOT / ".env", APP_ROOT / "config/review.yaml")
    start, end = _window(config, value)
    _load_proxy_environment(config.path("REVIEW_HERMES_PROXY_ENV_FILE"))
    client = GoogleReadClient(config.path("REVIEW_GOOGLE_CREDENTIAL_FILE"))
    calendar: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    errors: list[str] = []
    if config.policy["sources"]["google_calendar"]:
        try:
            calendar = _calendar(client, start, end, int(config.policy["sources"]["google_calendar_max_results"]), config.timezone)
        except GoogleReadError as exc:
            errors.append(f"google_calendar: {exc}")
    if config.policy["sources"]["google_tasks"]:
        try:
            tasks = _tasks(client, start, end, int(config.policy["sources"]["google_tasks_max_results"]))
        except GoogleReadError as exc:
            errors.append(f"google_tasks: {exc}")
    return {
        "date": start.date().isoformat(),
        "generated_at": datetime.now(config.timezone).isoformat(),
        "calendar": calendar,
        "tasks": tasks,
        "errors": errors,
    }


def main() -> int:
    """原子写入每日摘要，并只输出数量和错误数。"""

    args = _parser().parse_args()
    config = load_config(APP_ROOT / ".env", APP_ROOT / "config/review.yaml")
    report = collect(args.date)
    output_dir = config.path("REVIEW_GOOGLE_BRIEF_DIR")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{report['date']}.json"
    temporary = output.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)
    print(
        json.dumps(
            {
                "status": "ok",
                "date": report["date"],
                "calendar_count": len(report["calendar"]),
                "tasks_count": len(report["tasks"]),
                "error_count": len(report["errors"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps({"status": "error", "type": type(exc).__name__, "message": str(exc)[:240]}, ensure_ascii=False),
            file=sys.stderr,
        )
        raise SystemExit(2)
