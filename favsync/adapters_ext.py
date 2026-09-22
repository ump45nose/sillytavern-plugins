"""Optional EH and Xiaohongshu adapters.

The adapters deliberately expose the same scan/bundle contract as the core
engine.  Signed URLs and cookies are never logged or persisted outside the
item locator and the private state directory.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import http.cookiejar
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote, urlparse
import xml.etree.ElementTree as ET
import zipfile

import requests

from .common import SyncError, command
from .config import proxy_url
from .layout import component


def _valid_media(path):
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    if suffix == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if suffix in (".mp4", ".mov", ".heic"):
        return len(head) >= 12 and head[4:8] == b"ftyp"
    return False


def _json_command(argv, timeout, env=None):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=timeout, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        raise SyncError("tool_unavailable") from None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = None
    # Some xiaohongshu-cli commands intentionally return a non-zero code with
    # a structured JSON error.  Preserve that code for the adapter to classify.
    if payload is not None:
        return payload
    if result.returncode:
        text = result.stderr.decode("utf-8", "replace").lower()
        if any(x in text for x in ("verification", "captcha", "461", "471", "登录")):
            raise SyncError("verification_required")
        if any(x in text for x in ("429", "rate limit", "too many requests", "频率")):
            raise SyncError("rate_limited")
        raise SyncError("scan_incomplete")
    raise SyncError("invalid_export")


class XhsAdapter:
    def __init__(self, cfg, store=None):
        self.cfg, self.store = cfg, store
        self.begin_run()

    def begin_run(self):
        self._identity_cache = None
        self._last_request_at = 0.0
        self._discover_remaining = self.cfg["xhs"]["max_new_items_per_run"]
        self._detail_remaining = self.cfg["xhs"]["max_detail_items_per_run"]
        self._bundle_remaining = self.cfg["xhs"]["max_detail_items_per_run"]
        self._detail_failures = 0

    def _pace(self):
        low = float(self.cfg["xhs"]["request_delay_min_seconds"])
        high = float(self.cfg["xhs"]["request_delay_max_seconds"])
        if self._last_request_at:
            wait = random.uniform(low, high) - (time.monotonic() - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at = time.monotonic()

    def take_bundle_slot(self):
        if self._bundle_remaining <= 0:
            return False
        self._bundle_remaining -= 1
        return True

    def _env(self):
        env = os.environ.copy()
        home = Path(self.cfg["state_dir"]) / "xhs-home"
        cookie_dir = home / ".xiaohongshu-cli"
        cookie_dir.mkdir(parents=True, exist_ok=True)
        source = Path(self.cfg["state_dir"]) / "xhs-cookies.json"
        if not source.is_file():
            raise SyncError("auth_required")
        target = cookie_dir / "cookies.json"
        if not target.exists() or target.read_bytes() != source.read_bytes():
            target.write_bytes(source.read_bytes())
        env["HOME"] = str(home)
        return env

    @staticmethod
    def _note(note):
        item_id = str(note.get("note_id") or note.get("id") or note.get("noteId") or "")
        if not item_id:
            raise SyncError("invalid_export")
        user = note.get("user") or note.get("user_info") or {}
        author = user.get("nickname") or note.get("nickname") or "作者未知"
        stamp = note.get("time") or note.get("publish_time") or note.get("timestamp") or 0
        try:
            stamp = int(stamp) / (1000 if int(stamp) > 100000000000 else 1)
            published = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d") if stamp else "日期待定"
        except (ValueError, TypeError, OSError):
            published = "日期待定"
        token = note.get("xsec_token") or note.get("xsecToken") or ""
        url = f"https://www.xiaohongshu.com/explore/{item_id}"
        if token:
            url += "?xsec_token=" + quote(token, safe="") + "&xsec_source=pc_user"
        return {"id": item_id, "text": "", "assets": [], "bundle": True,
                "locator": {"url": url, "author": author, "published": published,
                            "naming": {"group": author, "date": published}}}

    def scan(self, source, cursor=0, start=None):
        # The list commands can currently exit with an internal traceback when
        # web_session has expired.  Check the structured status endpoint first
        # so the scheduler reports auth_required instead of scan_incomplete.
        self.identity()
        kind = "favorites" if source == "xhs_favorites" else "likes"
        records, seen_cursors, cursor_value = [], set(), ""
        account = self.cfg[source]["account"]
        for _page in range(self.cfg["xhs"]["max_pages_per_run"]):
            if self._discover_remaining <= 0:
                break
            argv = [self.cfg["xhs"]["cli_binary"], kind, "--json"]
            if cursor_value:
                argv += ["--cursor", cursor_value]
            self._pace()
            payload = _json_command(argv, self.cfg["command_timeout_seconds"], self._env())
            if not payload.get("ok"):
                code = str((payload.get("error") or {}).get("code", "scan_incomplete")).lower()
                if code in ("not_authenticated", "unauthenticated", "login_required", "auth_required", "session_expired"):
                    raise SyncError("auth_required")
                if code in ("verification_required", "captcha_required", "ip_blocked", "461", "471"):
                    raise SyncError("verification_required")
                if code in ("rate_limited", "too_many_requests", "429"):
                    raise SyncError("rate_limited")
                raise SyncError("scan_incomplete")
            data = payload.get("data") or {}
            page_records = [self._note(n) for n in data.get("notes", [])]
            page_seen = self.store.seen_ids(source, account, (r["id"] for r in page_records))
            fresh = [r for r in page_records if r["id"] not in page_seen]
            selected = fresh[:self._discover_remaining]
            records.extend(selected)
            self._discover_remaining -= len(selected)
            # A complete already-seen page is the durable incremental boundary.
            if page_records and len(page_seen) == len(page_records):
                break
            if not data.get("has_more"):
                break
            next_cursor = str(data.get("cursor") or "")
            if not next_cursor or next_cursor in seen_cursors:
                raise SyncError("scan_incomplete")
            seen_cursors.add(next_cursor)
            cursor_value = next_cursor
        return records, None

    def identity(self):
        if self._identity_cache is not None:
            return self._identity_cache
        self._pace()
        payload = _json_command([self.cfg["xhs"]["cli_binary"], "status", "--json"],
                                self.cfg["command_timeout_seconds"], self._env())
        if not payload.get("ok"):
            raise SyncError("auth_required")
        data = payload.get("data") or {}
        user = data.get("user") or payload.get("user") or {}
        user_id = str(user.get("id") or user.get("user_id") or "").strip()
        if not user_id or user.get("guest"):
            raise SyncError("auth_required")
        self._identity_cache = user_id
        return user_id

    def download_bundle(self, item, staging):
        locator = json.loads(item["locator"])
        cookie = (Path(self.cfg["state_dir"]) / "xhs-cookie.txt").read_text()
        proxy = proxy_url(self.cfg, "xhs")
        # The downloader runs in a bridged container, where the host's
        # 127.0.0.1 proxy would point back at the container itself. Its direct
        # route is usable; Favsync still applies the host proxy to media fetches.
        session = requests.Session(); session.trust_env = False
        data = self.store.xhs_detail(item["account"], item["item_id"],
                                     self.cfg["xhs"]["detail_cache_ttl_seconds"])
        if data is None:
            if self._detail_remaining <= 0:
                raise SyncError("deferred_request_budget")
            self._detail_remaining -= 1
            self._pace()
            body = {"url": locator["url"], "download": False, "cookie": cookie,
                    "proxy": None, "check_record": False}
            try:
                response = session.post(self.cfg["xhs"]["downloader_url"].rstrip("/") + "/xhs/detail",
                                        json=body, timeout=self.cfg["command_timeout_seconds"])
                response.raise_for_status(); payload = response.json()
            except Exception:
                raise SyncError("xhs_downloader_unavailable") from None
            data = payload.get("data")
            if not data:
                self._detail_failures += 1
                if self._detail_failures >= 2:
                    raise SyncError("risk_control_suspected")
                raise SyncError("content_unavailable")
            self._detail_failures = 0
            self.store.save_xhs_detail(item["account"], item["item_id"], data)
        urls = []
        def walk(value, key=""):
            if isinstance(value, dict):
                for k, v in value.items(): walk(v, k)
            elif isinstance(value, list):
                for v in value: walk(v, key)
            elif isinstance(value, str) and key in ("下载地址", "动图地址") and value.startswith("http"):
                urls.append(value)
        walk(data)
        urls = list(dict.fromkeys(urls))
        if not urls:
            self.store.delete_xhs_detail(item["account"], item["item_id"])
            raise SyncError("media_unavailable")
        author = str(data.get("作者昵称") or locator.get("author") or "作者未知")
        raw_published = str(data.get("发布时间") or "")
        published = raw_published[:10] if len(raw_published) >= 10 and raw_published[4:5] == "-" and raw_published[7:8] == "-" else ""
        if not published:
            try:
                stamp = float(data.get("时间戳") or 0)
                published = datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m-%d") if stamp else "日期未知"
            except (ValueError, TypeError, OSError):
                published = "日期未知"
        ordinal = self.store.xhs_ordinal(item["account"], author, published, item["item_id"])
        proposed = f"{component(author)}_{published}_{ordinal}"
        output = Path(self.cfg["xhs"]["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        base = self.store.xhs_stem(item["account"], author, published, item["item_id"], proposed, output)
        results = []
        for index, url in enumerate(urls, 1):
            suffix = Path(urlparse(url).path).suffix.lower()
            if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".mp4", ".mov"):
                suffix = ".mp4" if "video" in url.lower() else ".jpg"
            name = base + (f"_{index:03d}" if len(urls) > 1 else "") + suffix
            target = staging / name
            try:
                with session.get(url, headers={"Cookie": cookie, "Referer": locator["url"]},
                                 proxies={"http": proxy, "https": proxy} if proxy else None,
                                 stream=True, timeout=120) as media:
                    if media.status_code in (401, 403, 404):
                        self.store.delete_xhs_detail(item["account"], item["item_id"])
                        raise SyncError("media_url_expired")
                    media.raise_for_status()
                    with target.open("wb") as out:
                        for chunk in media.iter_content(1024 * 1024):
                            if chunk: out.write(chunk)
            except SyncError:
                raise
            except Exception:
                raise SyncError("download_failed") from None
            if not target.stat().st_size or not _valid_media(target):
                raise SyncError("download_invalid_file")
            results.append(target)
        final_paths = []
        for target in results:
            with target.open("rb") as media:
                os.fsync(media.fileno())
            final = output / target.name
            os.replace(target, final)
            final_paths.append(final)
        try:
            staging.rmdir()
        except OSError:
            pass
        return final_paths


class EhAdapter:
    def __init__(self, cfg, store=None):
        self.cfg, self.store = cfg, store

    @contextmanager
    def config_file(self, destination=None):
        extractor = {"cookies": str(Path(self.cfg["state_dir"]) / "eh-cookies.txt"),
                     "original": True, "gp": "stop", "limits-action": "stop",
                     "retries": 4, "retry-wait": "5-30", "timeout": 30, "proxy-env": False}
        if proxy := proxy_url(self.cfg, "eh"):
            extractor["proxy"] = proxy.replace("socks5://", "socks5h://")
        if destination:
            extractor.update({"base-directory": str(destination), "directory": [],
                              "filename": "{num:04}.{extension}"})
        cfg = {"extractor": {"exhentai": extractor}, "output": {"progress": False}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=self.cfg["state_dir"], delete=False) as f:
            json.dump(cfg, f); name = f.name
        try: yield name
        finally: Path(name).unlink(missing_ok=True)

    def _events(self, url):
        with self.config_file() as config, tempfile.TemporaryFile() as output:
            command([sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config, "-j", url],
                    self.cfg["command_timeout_seconds"], output)
            output.seek(0)
            try:
                events = json.load(output)
            except ValueError:
                raise SyncError("invalid_export") from None
            errors = [e[-1] for e in events if isinstance(e, list) and e and e[0] == -1]
            if errors:
                names = {str(e.get("error", "")) for e in errors if isinstance(e, dict)}
                if names & {"AuthenticationError", "AuthorizationError"}:
                    raise SyncError("auth_required")
                raise SyncError("scan_incomplete")
            return events

    def scan(self, source, cursor=0, start=None):
        events = self._events("https://exhentai.org/favorites.php")
        records = {}
        for event in events:
            if not isinstance(event, list) or event[0] not in (2, 3):
                continue
            meta = event[-1]
            gid = str(meta.get("gallery_id") or meta.get("gid") or "")
            token = meta.get("gallery_token") or meta.get("token")
            if gid.isdigit() and token:
                records[gid] = {"id": gid, "text": "", "assets": [], "bundle": True,
                                "locator": {"url": f"https://exhentai.org/g/{gid}/{token}/"}}
        return list(records.values()), None

    def identity(self):
        path = Path(self.cfg["state_dir"]) / "eh-cookies.txt"
        try:
            jar = http.cookiejar.MozillaCookieJar(str(path))
            jar.load(ignore_discard=True, ignore_expires=True)
            member_id = next(c.value for c in jar if c.name == "ipb_member_id" and c.value)
        except (OSError, StopIteration, http.cookiejar.LoadError):
            raise SyncError("auth_required") from None
        return member_id

    @staticmethod
    def _tags(meta):
        grouped = {}
        raw = meta.get("tags") or []
        if isinstance(raw, dict):
            grouped.update({str(k): list(v) for k, v in raw.items()})
        else:
            for tag in raw:
                kind, separator, value = str(tag).partition(":")
                grouped.setdefault(kind if separator else "tag", []).append(value if separator else kind)
        for key, values in meta.items():
            if key.startswith("tags_") and isinstance(values, list):
                grouped[key[5:]] = values
        return grouped

    @staticmethod
    def _comicinfo(meta, count, url):
        root = ET.Element("ComicInfo")
        def add(name, value):
            if value not in (None, "", []): ET.SubElement(root, name).text = ", ".join(value) if isinstance(value, list) else str(value)
        tags = EhAdapter._tags(meta)
        title = meta.get("title") or meta.get("title_en") or str(meta.get("gallery_id", ""))
        add("Series", title); add("Title", title); add("AlternateSeries", meta.get("title_jpn"))
        add("Writer", tags.get("artist", [])); add("Teams", tags.get("group", [])); add("Characters", tags.get("character", []))
        rest = [meta.get("eh_category") or meta.get("category", "")] + [f"{k}:{v}" for k, values in tags.items() if k not in ("artist","group","character") for v in values]
        add("Genre", [x for x in rest if x]); add("PageCount", count); add("CommunityRating", meta.get("rating")); add("Web", url)
        add("LanguageISO", meta.get("lang") or meta.get("language"))
        try:
            raw_date = meta.get("date")
            day = (datetime.fromtimestamp(float(raw_date), timezone.utc) if str(raw_date).replace('.', '', 1).isdigit()
                   else datetime.fromisoformat(str(raw_date).replace("Z", "+00:00")))
            add("Year", day.year); add("Month", day.month); add("Day", day.day)
        except (TypeError, ValueError, OSError): pass
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def download_bundle(self, item, staging):
        locator = json.loads(item["locator"]); url = locator["url"]
        events = self._events(url)
        metas = [e[-1] for e in events if isinstance(e, list) and e[0] in (2,3)]
        file_events = [e for e in events if isinstance(e,list) and e[0] == 3]
        file_meta = [e[-1] for e in file_events]
        if not file_events:
            raise SyncError("invalid_export")
        # `image_token` alone identifies the resized route. Strict mode requires
        # the extractor's explicit full/original URL for every page.
        for event in file_events:
            candidate = str(event[1] if len(event) > 2 else "")
            if not candidate or "fullimg" not in candidate:
                raise SyncError("original_unavailable")
        paused = self.store.setting("low_disk_paused") == "1"
        threshold = self.cfg["storage"]["resume_free_bytes"] if paused else self.cfg["storage"]["min_free_bytes"]
        if shutil.disk_usage(self.cfg["eh"]["output_dir"]).free < threshold:
            self.store.setting("low_disk_paused", "1")
            raise SyncError("paused_low_disk")
        # Keep transport in the pinned gallery-dl build.  Its EH downloader
        # handles the image host's TLS behavior and resumes .part files, while
        # Favsync still validates that every selected URL is an original above.
        with self.config_file(staging) as config:
            command([sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config, url],
                    self.cfg["command_timeout_seconds"], warnings_are_errors=True)
        images = sorted(p for p in staging.iterdir() if p.is_file() and p.suffix.lower() not in (".zip", ".xml", ".part"))
        expected = int((metas[0] if metas else {}).get("filecount") or len(file_meta))
        if len(images) != expected or any(not p.stat().st_size or not _valid_media(p) for p in images):
            raise SyncError("incomplete_gallery")
        meta = metas[0]; tags = self._tags(meta)
        artist = component((tags.get("artist") or ["Unknown"])[0]) or "Unknown"
        title = component(meta.get("title") or meta.get("title_en") or item["item_id"], 180)
        final = self.store.eh_path(item["account"], item["item_id"], artist, title,
                                   self.cfg["eh"]["output_dir"])
        final.parent.mkdir(parents=True, exist_ok=True)
        temp = staging / (final.name + ".tmp")
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for page, image in enumerate(images, 1): archive.write(image, f"{page:04d}{image.suffix.lower()}")
            archive.writestr("ComicInfo.xml", self._comicinfo(meta, expected, url))
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() or len(archive.namelist()) != expected + 1:
                raise SyncError("zip_validation_failed")
        os.replace(temp, final)
        shutil.rmtree(staging, ignore_errors=True)
        return [final]
