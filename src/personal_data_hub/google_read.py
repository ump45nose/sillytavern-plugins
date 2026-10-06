from __future__ import annotations

import json, os

from pathlib import Path

from typing import Any

from urllib.error import HTTPError, URLError

from urllib.parse import urlencode

from urllib.request import Request, urlopen

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
