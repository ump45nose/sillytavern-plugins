from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo
import re
import tomllib
from urllib.parse import urlparse


SOURCES = ("telegram", "telegram_notice", "x_bookmarks", "x_likes", "eh_favorites", "xhs_favorites", "xhs_likes",
           "pixiv_art_public", "pixiv_art_private", "pixiv_novel_public", "pixiv_novel_private",
           "wallabag_entries")
SOURCE_PLATFORM = {"telegram": "telegram", "telegram_notice": "telegram_notice", "x_bookmarks": "x", "x_likes": "x",
                   "eh_favorites": "eh", "xhs_favorites": "xhs", "xhs_likes": "xhs",
                   "pixiv_art_public": "pixiv", "pixiv_art_private": "pixiv",
                   "pixiv_novel_public": "pixiv", "pixiv_novel_private": "pixiv",
                   "wallabag_entries": "wallabag"}
APPLICATIONS = ("telegram", "x", "eh", "xhs", "pixiv", "wallabag", "cookiecloud")


def telegram_accounts(cfg):
    """Keep the original account and add isolated, optionally overridden profiles."""
    base = {k: v for k, v in cfg["telegram"].items() if k != "accounts"}
    profiles = [base]
    for override in cfg["telegram"].get("accounts", []):
        profiles.append({**base, **override})
    return profiles


def telegram_config(cfg, account):
    for profile in telegram_accounts(cfg):
        if profile["account"] == account:
            return {**cfg, "telegram": profile}
    raise ValueError("Telegram account is not configured")


def start_timestamp(value, timezone):
    if not value:
        return None
    day = date.fromisoformat(str(value))
    return int(datetime.combine(day, time.min, ZoneInfo(timezone)).timestamp())


def proxy_url(cfg, application):
    """Return an application's proxy, defaulting new applications to proxied."""
    proxy = cfg["proxy"]
    enabled = proxy["applications"].get(application, proxy["default_enabled"])
    return proxy["url"] if enabled else None


def load(path):
    path = Path(path).resolve()
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    cfg.setdefault("timezone", "Asia/Taipei")
    ZoneInfo(cfg["timezone"])
    cfg.setdefault("interval_seconds", 28800)
    cfg.setdefault("command_timeout_seconds", 3600)
    cfg.setdefault('markdown_scope', 'platform')
    if cfg['markdown_scope'] not in ('platform', 'combined'):
        raise ValueError('markdown_scope must be platform or combined')
    proxy = cfg.setdefault("proxy", {})
    proxy.setdefault("url", "socks5://127.0.0.1:7890")
    proxy.setdefault("default_enabled", True)
    applications = proxy.setdefault("applications", {})
    applications.setdefault("cookiecloud", False)
    if not isinstance(proxy["default_enabled"], bool):
        raise ValueError("proxy.default_enabled must be boolean")
    if not isinstance(applications, dict) or any(
            not isinstance(name, str) or not isinstance(enabled, bool)
            for name, enabled in applications.items()):
        raise ValueError("proxy.applications must map application names to booleans")
    parsed_proxy = urlparse(proxy["url"])
    if parsed_proxy.scheme not in {"http", "https", "socks4", "socks5", "socks5h"} or not parsed_proxy.hostname:
        raise ValueError("proxy.url must be an HTTP or SOCKS proxy URL")
    for key, default in (("state_dir", "state"), ("download_dir", "downloads")):
        p = Path(cfg.get(key, default)).expanduser()
        cfg[key] = str(p if p.is_absolute() else path.parent / p)
    for source in SOURCES:
        section = cfg.setdefault(source, {})
        section.setdefault("enabled", False)
        section.setdefault("account", "personal")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", section["account"]):
            raise ValueError(f"invalid account label: {source}")
        if source in ("telegram", "x_bookmarks"):
            section.setdefault("start_date", "")
            start_timestamp(section["start_date"], cfg["timezone"])
    if cfg["x_bookmarks"]["account"] != cfg["x_likes"]["account"]:
        raise ValueError("X bookmarks and likes must use the same account label")
    additional = cfg["telegram"].get("accounts", [])
    if not isinstance(additional, list) or any(not isinstance(p, dict) or "account" not in p for p in additional):
        raise ValueError("telegram.accounts must be an array of account tables")
    for profile in [cfg['telegram'], *additional]:
        if 'download_dir' in profile:
            raise ValueError('use the shared top-level download_dir, not telegram.download_dir')
    labels = set()
    for profile in telegram_accounts(cfg):
        label = profile["account"]
        if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", label) or label in labels:
            raise ValueError("Telegram account labels must be unique safe names")
        labels.add(label)
        if not isinstance(profile["enabled"], bool):
            raise ValueError("Telegram enabled must be boolean")
        start_timestamp(profile["start_date"], cfg["timezone"])
    notice = cfg["telegram_notice"]
    notice.setdefault("chat", "@yuwk_notice_bot")
    if not re.fullmatch(r"@[A-Za-z0-9_]{5,32}", notice["chat"]):
        raise ValueError("telegram_notice.chat must be a Telegram username")
    if notice["account"] not in labels:
        raise ValueError("telegram_notice.account must reference a configured Telegram account")
    x = cfg.setdefault("x", {})
    x.setdefault("username", "")
    if x["username"] and not re.fullmatch(r"[A-Za-z0-9_]{1,15}", x["username"]):
        raise ValueError("invalid X username")
    storage = cfg.setdefault("storage", {})
    storage.setdefault("min_free_bytes", 214748364800)
    storage.setdefault("resume_free_bytes", 236223201280)
    if not 0 <= storage["min_free_bytes"] <= storage["resume_free_bytes"]:
        raise ValueError("invalid storage thresholds")
    eh = cfg.setdefault("eh", {})
    eh.setdefault("output_dir", "/eh-downloads")
    eh.setdefault("strict_original", True)
    xhs = cfg.setdefault("xhs", {})
    xhs.setdefault("output_dir", str(Path(cfg["download_dir"]) / "Xiaohongshu"))
    xhs.setdefault("cli_binary", "xhs")
    xhs.setdefault("downloader_url", "http://127.0.0.1:5556")
    xhs.setdefault("staging_dir", str(Path(cfg["state_dir"]) / "xhs-staging"))
    xhs.setdefault("max_pages_per_run", 2)
    xhs.setdefault("max_new_items_per_run", 5)
    xhs.setdefault("max_detail_items_per_run", 5)
    xhs.setdefault("request_delay_min_seconds", 15)
    xhs.setdefault("request_delay_max_seconds", 30)
    xhs.setdefault("detail_cache_ttl_seconds", 86400)
    for name in ("max_pages_per_run", "max_new_items_per_run", "max_detail_items_per_run"):
        if not isinstance(xhs[name], int) or not 1 <= xhs[name] <= 10:
            raise ValueError(f"xhs.{name} must be between 1 and 10")
    for name in ("request_delay_min_seconds", "request_delay_max_seconds"):
        if not isinstance(xhs[name], (int, float)) or xhs[name] < 0:
            raise ValueError(f"xhs.{name} must be non-negative")
    if xhs["request_delay_min_seconds"] > xhs["request_delay_max_seconds"]:
        raise ValueError("xhs request delay range is invalid")
    if not isinstance(xhs["detail_cache_ttl_seconds"], int) or xhs["detail_cache_ttl_seconds"] < 0:
        raise ValueError("xhs.detail_cache_ttl_seconds must be non-negative")
    pixiv = cfg.setdefault("pixiv", {})
    pixiv.setdefault("uid", "")
    pixiv.setdefault("start_date", "")
    start_timestamp(pixiv["start_date"], cfg["timezone"])
    if pixiv["uid"] and not str(pixiv["uid"]).isdigit():
        raise ValueError("pixiv.uid must be numeric")
    pixiv["uid"] = str(pixiv["uid"])
    pixiv.setdefault("refresh_token_file", "/run/favsync-secrets/pixiv-refresh-token")
    pixiv.setdefault("cookie_file", "")
    pixiv.setdefault("picture_dir", str(Path(cfg["download_dir"]) / "Pixiv" / "picture"))
    pixiv.setdefault("novel_dir", str(Path(cfg["download_dir"]) / "Pixiv" / "noval"))
    pixiv.setdefault("ugoira_enabled", False)
    pixiv.setdefault("novel_embeds", True)
    wallabag = cfg.setdefault("wallabag", {})
    wallabag.setdefault("base_url", "http://127.0.0.1:18081")
    wallabag.setdefault("credentials_file", "/run/favsync-secrets/wallabag.json")
    wallabag.setdefault("output_dir", str(Path(cfg["download_dir"]) / "Wallabag"))
    wallabag.setdefault("tags", [])
    wallabag.setdefault("per_page", 50)
    wallabag.setdefault("min_content_chars", 100)
    wallabag.setdefault("export_timeout_seconds", 180)
    if not isinstance(wallabag["tags"], list) or any(not isinstance(tag, str) for tag in wallabag["tags"]):
        raise ValueError("wallabag.tags must be an array of strings")
    if not isinstance(wallabag["per_page"], int) or not 1 <= wallabag["per_page"] <= 100:
        raise ValueError("wallabag.per_page must be between 1 and 100")
    if not isinstance(wallabag["min_content_chars"], int) or wallabag["min_content_chars"] < 1:
        raise ValueError("wallabag.min_content_chars must be positive")
    if not isinstance(wallabag["export_timeout_seconds"], int) or wallabag["export_timeout_seconds"] < 30:
        raise ValueError("wallabag.export_timeout_seconds must be at least 30")
    download_root = Path(cfg["download_dir"]).resolve()
    for name in ("picture_dir", "novel_dir"):
        if not Path(pixiv[name]).resolve().is_relative_to(download_root):
            raise ValueError(f"pixiv.{name} must be below download_dir")
    if not Path(wallabag["output_dir"]).resolve().is_relative_to(download_root):
        raise ValueError("wallabag.output_dir must be below download_dir")
    cc = cfg.setdefault("cookiecloud", {})
    cc.setdefault("enabled", False)
    cc.setdefault("interval_seconds", 28800)
    cc.setdefault("url", "http://127.0.0.1:18088")
    cc.setdefault("credentials_file", "secrets/cookiecloud.json")
    cp = Path(cc["credentials_file"])
    cc["credentials_file"] = str(cp if cp.is_absolute() else path.parent / cp)
    for value in (cfg["interval_seconds"], cfg["command_timeout_seconds"], cc["interval_seconds"]):
        if not isinstance(value, int) or value < 1:
            raise ValueError("intervals and timeout must be positive integers")
    return cfg
