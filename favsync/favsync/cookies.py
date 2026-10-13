import base64
import hashlib
import http.cookiejar
import json
from pathlib import Path
import time
from urllib.parse import quote
import requests

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .common import SyncError, atomic_write
from .config import proxy_url


def decrypt(payload, uuid, password):
    secret = hashlib.md5(f"{uuid}-{password}".encode()).hexdigest()[:16].encode()
    encrypted = base64.b64decode(payload["encrypted"], validate=True)
    # Older official CookieCloud servers persist only `encrypted`, dropping
    # the algorithm hint. CryptoJS legacy envelopes carry an explicit header.
    method = payload.get("crypto_type") or ("legacy" if encrypted.startswith(b"Salted__") else "aes-128-cbc-fixed")
    if method == "aes-128-cbc-fixed":
        key, iv, ciphertext = secret, bytes(16), encrypted
    elif method == "legacy":
        if encrypted[:8] != b"Salted__":
            raise ValueError("invalid legacy envelope")
        salt, ciphertext = encrypted[8:16], encrypted[16:]
        material = previous = b""
        while len(material) < 48:
            previous = hashlib.md5(previous + secret + salt).digest()
            material += previous
        key, iv = material[:32], material[32:48]
    else:
        raise ValueError("unsupported CookieCloud encryption")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = cipher.update(ciphertext) + cipher.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return json.loads(unpad.update(padded) + unpad.finalize())


def _selected(data, domains):
    result = []
    for cookies in data.get("cookie_data", {}).values():
        for c in cookies:
            domain = c.get("domain", "").lstrip(".").lower()
            if not any(domain == d or domain.endswith("." + d) for d in domains):
                continue
            expiry = int(c.get("expirationDate", 0))
            if not expiry or expiry > time.time():
                result.append(c)
    return result


def netscape_for(data, domains, required=()):
    cookies = _selected(data, domains)
    if required and not all(any(c.get("name") == name and c.get("value") for c in cookies) for name in required):
        raise SyncError("cookiecloud_missing_login")
    lines = ["# Netscape HTTP Cookie File"]
    for c in sorted(cookies, key=lambda x: (x.get("domain", ""), x.get("path", "/"), x.get("name", ""))):
        values = (c.get("name", ""), c.get("value", ""), c.get("path", "/"))
        if any(ch in part for part in values for ch in ("\n", "\r", "\t")):
            raise ValueError("invalid cookie")
        domain = c.get("domain", "")
        if c.get("httpOnly"):
            domain = "#HttpOnly_" + domain
        lines.append("\t".join((domain, "TRUE" if c.get("domain", "").startswith(".") else "FALSE",
                                c.get("path", "/"), "TRUE" if c.get("secure", True) else "FALSE",
                                str(int(c.get("expirationDate", 0))) if c.get("expirationDate") else "",
                                c["name"], c["value"])))
    return ("\n".join(lines) + "\n").encode()


def cookie_header(data, domains, required=()):
    cookies = _selected(data, domains)
    if required and not all(any(c.get("name") == name and c.get("value") for c in cookies) for name in required):
        raise SyncError("cookiecloud_missing_login")
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def cookie_map(data, domains, required=()):
    cookies = _selected(data, domains)
    if required and not all(any(c.get("name") == name and c.get("value") for c in cookies) for name in required):
        raise SyncError("cookiecloud_missing_login")
    return {c["name"]: c["value"] for c in cookies}


def eh_netscape(data):
    """EH auth cookies are shared, but Chrome may persist them only on e-hentai."""
    cookies = _selected(data, ("e-hentai.org", "exhentai.org"))
    auth = {c.get("name"): c for c in cookies if c.get("name") in ("ipb_member_id", "ipb_pass_hash")}
    if not all(auth.get(name, {}).get("value") for name in ("ipb_member_id", "ipb_pass_hash")):
        raise SyncError("cookiecloud_missing_login")
    mirrored = list(cookies)
    for domain in (".e-hentai.org", ".exhentai.org"):
        for cookie in auth.values():
            clone = dict(cookie); clone["domain"] = domain
            mirrored.append(clone)
    return netscape_for({"cookie_data": {"eh": mirrored}}, ("e-hentai.org", "exhentai.org"),
                        ("ipb_member_id", "ipb_pass_hash"))


def netscape(data):
    selected = {}
    for cookies in data["cookie_data"].values():
        for c in cookies:
            domain = c["domain"].lstrip(".").lower()
            # Never import unrelated cookies or LocalStorage.
            if domain not in ("x.com", "twitter.com"):
                continue
            expiry = int(c.get("expirationDate", 0))
            if expiry and expiry <= time.time():
                continue
            name, value, path = c["name"], c["value"], c.get("path", "/")
            if any(ch in part for part in (name, value, path) for ch in ("\n", "\r", "\t")):
                raise ValueError("invalid cookie")
            key = (path, name)
            if domain == "x.com" or key not in selected:
                selected[key] = (value, expiry, bool(c.get("secure", True)), bool(c.get("httpOnly")))
    if not all(selected.get(("/", key), ("",))[0] for key in ("auth_token", "ct0")):
        raise SyncError("cookiecloud_missing_x_login")
    lines = ["# Netscape HTTP Cookie File"]
    for (path, name), (value, expiry, secure, httponly) in sorted(selected.items()):
        domain = ("#HttpOnly_" if httponly else "") + ".x.com"
        # Empty expiry is a session cookie; numeric zero means expired to MozillaCookieJar.
        lines.append("\t".join((domain, "TRUE", path, "TRUE" if secure else "FALSE", str(expiry) if expiry else "", name, value)))
    return ("\n".join(lines) + "\n").encode()


def sync(cfg):
    cc = cfg["cookiecloud"]
    try:
        secret = json.loads(Path(cc["credentials_file"]).read_text())
        url = cc["url"].rstrip("/") + "/get/" + quote(secret["uuid"], safe="")
        # Password never leaves this process. Download encrypted envelope only.
        proxy = proxy_url(cfg, "cookiecloud")
        session = requests.Session()
        session.trust_env = False
        if proxy:
            session.proxies.update({"http": proxy, "https": proxy})
        with session.get(url, timeout=30, stream=True) as response:
            response.raise_for_status()
            chunks = []
            size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 4 * 1024 * 1024:
                    raise ValueError("oversized response")
                chunks.append(chunk)
            raw = b"".join(chunks)
        data = decrypt(json.loads(raw), secret["uuid"], secret["password"])
        jobs = []
        if cfg.get("x_bookmarks", {}).get("enabled") or cfg.get("x_likes", {}).get("enabled"):
            jobs.append(("x", lambda: {"x-cookies.txt": netscape(data)}))
        if cfg.get("xhs_favorites", {}).get("enabled") or cfg.get("xhs_likes", {}).get("enabled"):
            def xhs():
                header = cookie_header(data, ("xiaohongshu.com",), ("a1",))
                saved = {**cookie_map(data, ("xiaohongshu.com",), ("a1",)), "saved_at": int(time.time())}
                return {"xhs-cookies.json": json.dumps(saved, ensure_ascii=False).encode(),
                        "xhs-cookie.txt": header.encode()}
            jobs.append(("xhs", xhs))
        if cfg.get("eh_favorites", {}).get("enabled"):
            jobs.append(("eh", lambda: {"eh-cookies.txt": eh_netscape(data)}))
        results = {}
        for platform, build in jobs:
            try:
                for name, result in build().items():
                    target = Path(cfg["state_dir"]) / name
                    if not target.exists() or target.read_bytes() != result:
                        atomic_write(target, result)
                results[platform] = "ok"
            except (SyncError, ValueError, KeyError):
                # Keep the last valid platform file. Other platforms can still
                # authenticate from this same CookieCloud envelope.
                results[platform] = "missing_login"
        return results
    except SyncError:
        raise
    except Exception:
        raise SyncError("cookiecloud_sync_failed") from None


def fingerprint(cfg):
    path = Path(cfg["state_dir"]) / "x-cookies.txt"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def identity(cfg):
    """An account switch must not silently merge with a different likes baseline."""
    path = Path(cfg["state_dir"]) / "x-cookies.txt"
    try:
        jar = http.cookiejar.MozillaCookieJar(str(path))
        jar.load(ignore_discard=True)
        values = {c.name: c.value for c in jar if c.domain.lstrip(".") == "x.com"}
        if not values.get("auth_token") or not values.get("ct0"):
            raise ValueError("missing cookie")
        # twid is a stable account ID; it may be absent in a minimal manual jar.
        return values.get("twid")
    except Exception:
        raise SyncError("auth_required") from None
