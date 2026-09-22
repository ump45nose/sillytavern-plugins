"""One-time Pixiv authorization with persistent gallery-dl token caching."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import pickle
import sqlite3
import subprocess
import sys

import requests

from .common import SyncError
from .config import proxy_url


def _cached_refresh_token(cache_file):
    try:
        with sqlite3.connect(cache_file) as db:
            row = db.execute(
                "SELECT value FROM data WHERE key LIKE ? ORDER BY rowid DESC LIMIT 1",
                ("gallery_dl.extractor.pixiv._refresh_token_cache-%",),
            ).fetchone()
        value = row[0] if row else None
        token = pickle.loads(value) if isinstance(value, bytes) else json.loads(value)
    except (OSError, sqlite3.Error, ValueError, TypeError, pickle.UnpicklingError, EOFError):
        token = None
    if not isinstance(token, str) or not token:
        raise SyncError("pixiv_authorization_not_saved")
    return token


def _identity(cfg, refresh_token):
    # Keep these values sourced from the pinned gallery-dl build rather than
    # duplicating an independently maintained Pixiv client registration.
    from gallery_dl.extractor.pixiv import PixivAppAPI

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    headers = {
        "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
        "X-Client-Time": now,
        "X-Client-Hash": hashlib.md5((now + PixivAppAPI.HASH_SECRET).encode()).hexdigest(),
    }
    session = requests.Session()
    session.trust_env = False
    if proxy := proxy_url(cfg, "pixiv"):
        proxy = proxy.replace("socks5://", "socks5h://")
        session.proxies.update({"http": proxy, "https": proxy})
    try:
        response = session.post(
            "https://oauth.secure.pixiv.net/auth/token",
            headers=headers,
            data={
                "client_id": PixivAppAPI.CLIENT_ID,
                "client_secret": PixivAppAPI.CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "get_secure_url": "1",
            },
            timeout=60,
        )
        response.raise_for_status()
        user = response.json()["response"]["user"]
        uid = str(user["id"])
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise SyncError("pixiv_identity_failed") from None
    if not uid.isdigit():
        raise SyncError("pixiv_identity_failed")
    return {"uid": uid, "account": str(user.get("account") or ""),
            "name": str(user.get("name") or "")}


def _save_identity(cfg, identity):
    destination = Path(cfg["state_dir"]) / "pixiv-account.json"
    temp = destination.with_suffix(".json.tmp")
    temp.write_text(json.dumps(identity, ensure_ascii=False) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, destination)


def login(cfg):
    """Run gallery-dl OAuth, hide the token, and persist the detected UID."""
    home = Path(os.environ.get("HOME", "~")).expanduser()
    cache_file = home / ".cache" / "gallery-dl" / "cache.sqlite3"
    try:
        identity = _identity(cfg, _cached_refresh_token(cache_file))
    except SyncError:
        identity = None
    if identity:
        _save_identity(cfg, identity)
        print(f"Pixiv 已登录：UID {identity['uid']}；后续 access token 自动刷新。")
        return 0

    print("浏览器完成 Pixiv 登录后，复制回调页地址栏中的完整 URL（或 code）到这里。")
    print("授权码仅用于本次交换；refresh token 不会显示在终端。")
    argv = [sys.executable, "-m", "gallery_dl"]
    if proxy := proxy_url(cfg, "pixiv"):
        argv += ["--proxy", proxy.replace("socks5://", "socks5h://")]
    argv += ["oauth:pixiv"]
    process = subprocess.Popen(
        argv,
        stdin=None, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    hide_value = False
    assert process.stdout is not None
    for line in process.stdout:
        if "Your 'refresh-token'" in line:
            hide_value = True
            print("Pixiv 已授权，正在安全保存凭据。")
            continue
        if hide_value and line.strip():
            hide_value = False
            continue
        if not hide_value:
            print(line, end="", flush=True)
    if process.wait() != 0:
        raise SyncError("pixiv_authorization_failed")

    identity = _identity(cfg, _cached_refresh_token(cache_file))
    _save_identity(cfg, identity)
    print(f"Pixiv 登录完成：UID {identity['uid']}；后续 access token 自动刷新。")
    return 0
