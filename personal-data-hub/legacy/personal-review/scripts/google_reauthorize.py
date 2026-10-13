#!/usr/bin/env python3
"""通过桌面 OAuth 回环授权签发 Calendar/Tasks 只读刷新凭据。"""

from __future__ import annotations

import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
)


class AuthorizationError(RuntimeError):
    """表示 OAuth 授权失败；错误消息不得包含授权码或令牌。"""


def _parser() -> argparse.ArgumentParser:
    """构建只接受私有 ENV、目标凭据路径和回环端口的参数。"""

    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    return parser


def _read_private_env(path: Path) -> dict[str, str]:
    """读取 0600 私有 ENV，只返回 OAuth 客户端和联网代理变量。"""

    if path.stat().st_mode & 0o007:
        raise AuthorizationError("OAuth ENV 不得允许其他用户读取")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in {
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
        }:
            values[key] = value.strip().strip('"').strip("'")
    if not values.get("GOOGLE_CLIENT_ID") or not values.get("GOOGLE_CLIENT_SECRET"):
        raise AuthorizationError("OAuth ENV 缺少桌面客户端配置")
    return values


def _pkce_pair() -> tuple[str, str]:
    """生成 PKCE verifier 和 S256 challenge，避免授权码被截获后复用。"""

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _wait_for_code(port: int, expected_state: str) -> str:
    """在一次性 localhost 回调中校验 state 并取得授权码。"""

    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        """只处理一次 OAuth 回调，且不记录包含授权码的请求路径。"""

        def do_GET(self) -> None:  # noqa: N802
            """校验回调查询参数并向浏览器返回最小结果页。"""

            query = parse_qs(urlparse(self.path).query)
            if query.get("state", [""])[0] != expected_state:
                result["error"] = "OAuth state 校验失败"
                status = 400
            elif query.get("error"):
                result["error"] = "用户未完成 Google 授权"
                status = 400
            elif not query.get("code", [""])[0]:
                result["error"] = "Google 回调缺少授权码"
                status = 400
            else:
                result["code"] = query["code"][0]
                status = 200
            body = "授权完成，可以关闭此页面。" if status == 200 else "授权失败，请返回任务查看说明。"
            encoded = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            """禁止 HTTPServer 把带授权码的完整 URL 写入日志。"""

            del format, args

    server = HTTPServer(("127.0.0.1", port), CallbackHandler)
    # 人工同意可能需要切换标签页；保留十五分钟但只接受一次回调。
    server.timeout = 900
    server.handle_request()
    if "error" in result:
        raise AuthorizationError(result["error"])
    if "code" not in result:
        raise AuthorizationError("等待 Google 授权超时")
    return result["code"]


def _exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    verifier: str,
    redirect_uri: str,
) -> str:
    """交换一次性授权码并只返回长期 refresh token。"""

    payload = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    request = Request(TOKEN_ENDPOINT, data=payload, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(request, timeout=30) as response:
            token = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise AuthorizationError(f"Google 令牌交换失败：{type(exc).__name__}") from exc
    refresh_token = token.get("refresh_token") if isinstance(token, dict) else None
    if not isinstance(refresh_token, str) or not refresh_token:
        raise AuthorizationError("Google 未返回 refresh token")
    return refresh_token


def _write_credential(path: Path, values: dict[str, object]) -> Path | None:
    """先备份旧凭据，再以 0600 原子替换目标文件。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-personal-review-production")
        backup.write_bytes(path.read_bytes())
        os.chmod(backup, 0o600)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(values, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return backup


def main() -> int:
    """完成授权、持久化两个只读 scope，并且不输出任何令牌。"""

    args = _parser().parse_args()
    env = _read_private_env(args.env_file)
    client_id = env["GOOGLE_CLIENT_ID"]
    client_secret = env["GOOGLE_CLIENT_SECRET"]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy"):
        if env.get(key) and key not in os.environ:
            # cron 与 SSH 环境都可能缺少代理，令牌交换沿用 Hermes 的既有联网配置。
            os.environ[key] = env[key]
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    redirect_uri = f"http://127.0.0.1:{args.port}/"
    authorization_params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent',
        'include_granted_scopes': 'false',
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    }
    authorization_url = f"{AUTHORIZATION_ENDPOINT}?{urlencode(authorization_params)}"
    print(f"AUTHORIZATION_URL={authorization_url}", flush=True)
    code = _wait_for_code(args.port, state)
    refresh_token = _exchange_code(client_id, client_secret, code, verifier, redirect_uri)
    backup = _write_credential(
        args.credential_file,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "token_uri": TOKEN_ENDPOINT,
            "scopes": list(SCOPES),
        },
    )
    print("Google Calendar/Tasks 只读凭据已更新", flush=True)
    if backup is not None:
        print(f"旧凭据备份：{backup}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
