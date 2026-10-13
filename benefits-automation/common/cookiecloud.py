"""Optional one-shot CookieCloud reader, independent of any scheduler.

Only the requested site's cookies are returned. No sync service or disk cache.
Config is a private JSON file containing url, uuid, password (optional proxy).
"""

import base64
import hashlib
import json
import math
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

MAX_ENVELOPE = 4 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("cookiecloud_redirect_rejected")


def decrypt(payload, uuid, password):
    # Crypto is loaded only when this optional credential source is used.
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    secret = hashlib.md5(f"{uuid}-{password}".encode()).hexdigest()[:16].encode()
    encrypted = base64.b64decode(payload["encrypted"], validate=True)
    method = payload.get("crypto_type") or (
        "legacy" if encrypted.startswith(b"Salted__") else "aes-128-cbc-fixed"
    )
    if method == "aes-128-cbc-fixed":
        key, iv, ciphertext = secret, bytes(16), encrypted
    elif method == "legacy" and encrypted[:8] == b"Salted__":
        salt, ciphertext = encrypted[8:16], encrypted[16:]
        material = previous = b""
        while len(material) < 48:
            previous = hashlib.md5(previous + secret + salt).digest()
            material += previous
        key, iv = material[:32], material[32:48]
    else:
        raise ValueError("cookiecloud_encryption_unsupported")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    raw = cipher.update(ciphertext) + cipher.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return json.loads(unpad.update(raw) + unpad.finalize())


def read(config_file):
    with Path(config_file).open("rb") as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError("cookiecloud_config_invalid")
    config = json.loads(raw)
    url = urlsplit(config.get("url", ""))
    uuid, password = config.get("uuid"), config.get("password")
    if (url.scheme not in {"http", "https"} or not url.hostname or
            url.username or url.password or url.query or url.fragment or
            not isinstance(uuid, str) or not uuid or len(uuid) > 128 or
            any(x in uuid for x in "/?#\r\n") or
            not isinstance(password, str) or not password or len(password) > 1024):
        raise ValueError("cookiecloud_config_invalid")
    opener = build_opener(NoRedirect(), ProxyHandler(
        {"http": config["proxy"], "https": config["proxy"]} if config.get("proxy") else {}
    ))
    request = Request(config["url"].rstrip("/") + "/get/" + uuid)
    with opener.open(request, timeout=30) as response:
        if urlsplit(response.url).netloc != url.netloc:
            raise ValueError("cookiecloud_redirect_rejected")
        envelope = response.read(MAX_ENVELOPE + 1)
    if len(envelope) > MAX_ENVELOPE:
        raise ValueError("cookiecloud_response_limit")
    data = decrypt(json.loads(envelope), uuid, password)
    if not isinstance(data.get("cookie_data"), dict):
        raise ValueError("cookiecloud_inventory_invalid")
    return data["cookie_data"]


def site_rows(config_file, hostname):
    """Filter the requested host before exposing credentials to a caller."""
    hostname = hostname.lower()
    now = time.time()
    for rows in read(config_file).values():
        if not isinstance(rows, list):
            raise ValueError("cookiecloud_inventory_invalid")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("domain"), str):
                raise ValueError("cookiecloud_inventory_invalid")
            domain = row["domain"].lstrip(".").lower()
            if not domain or not (hostname == domain or
                    not row.get("hostOnly") and hostname.endswith("." + domain)):
                continue
            expires = row.get("expirationDate")
            if expires is not None:
                if (type(expires) not in (int, float) or not math.isfinite(expires)):
                    raise ValueError("cookiecloud_cookie_invalid")
                if expires <= now:
                    continue
            name, value = row.get("name"), row.get("value")
            path = row.get("path", "/")
            if (not isinstance(name, str) or not 0 < len(name) <= 256 or
                    not isinstance(value, str) or len(value) > 16384 or
                    any(x in name for x in "=;\r\n") or any(x in value for x in ";\r\n") or
                    not isinstance(path, str) or not path.startswith("/") or len(path) > 1024):
                raise ValueError("cookiecloud_cookie_invalid")
            yield row


def cookie_header(config_file, hostname, required=()):
    """Choose root-path cookies, preferring the most specific matching domain."""
    candidates = {}
    for row in site_rows(config_file, hostname):
        if row.get("path", "/") != "/":
            continue
        name, value = row["name"], row["value"]
        rank = len(row["domain"].lstrip("."))
        if name not in candidates or rank > candidates[name][0]:
            candidates[name] = rank, value
    if not candidates or any(name not in candidates for name in required):
        raise ValueError("cookiecloud_site_cookie_missing")
    header = "; ".join(name + "=" + item[1] for name, item in candidates.items())
    if len(header) > 65536:
        raise ValueError("cookiecloud_cookie_limit")
    return header


def browser_cookies(config_file, hostname):
    cookies = []
    for row in site_rows(config_file, hostname):
        cookies.append({"name": row["name"], "value": row["value"],
            "domain": row["domain"], "path": row.get("path", "/"),
            "secure": bool(row.get("secure")), "httpOnly": bool(row.get("httpOnly")),
            "expires": row.get("expirationDate", -1)})
        if len(cookies) > 300:
            raise ValueError("cookiecloud_cookie_limit")
    if not cookies or len(cookies) > 300:
        raise ValueError("cookiecloud_site_cookie_missing")
    return cookies
