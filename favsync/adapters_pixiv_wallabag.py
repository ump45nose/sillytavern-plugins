"""Pixiv bookmark bundles and wallabag EPUB exports."""
from contextlib import contextmanager
from datetime import datetime
from html.parser import HTMLParser
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET
import zipfile

import requests

from .adapters_ext import _valid_media
from .common import SyncError, command
from .config import proxy_url
from .layout import component


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.images = []

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "img":
            value = dict(attrs).get("src")
            if value:
                self.images.append(value)


def _html_summary(value):
    parser = _TextParser()
    try:
        parser.feed(value or "")
    except Exception:
        pass
    return " ".join(parser.text), parser.images


def _series_title(meta):
    value = meta.get("series")
    if isinstance(value, dict):
        return str(value.get("title") or value.get("name") or "")
    return str(value or "")


class PixivAdapter:
    def __init__(self, cfg, store=None):
        self.cfg, self.store = cfg, store

    def _token(self):
        path = Path(self.cfg["pixiv"]["refresh_token_file"])
        try:
            token = path.read_text().strip()
        except OSError:
            token = ""
        # pixiv-login stores the refresh token in gallery-dl's persistent,
        # mode-0600 cache.  Keep compatibility with an explicit legacy file.
        return token or "cache"

    def _uid(self):
        if uid := str(self.cfg["pixiv"].get("uid") or ""):
            return uid
        try:
            payload = json.loads((Path(self.cfg["state_dir"]) / "pixiv-account.json").read_text())
            uid = str(payload.get("uid") or "")
        except (OSError, ValueError, TypeError):
            uid = ""
        if not uid.isdigit():
            raise SyncError("auth_required")
        return uid

    def identity(self):
        return self._uid()

    @contextmanager
    def config_file(self, destination=None):
        common = {"refresh-token": self._token(), "metadata": False,
                  "metadata-bookmark": False, "comments": False,
                  "retries": 4, "retry-wait": "5-30", "timeout": 60,
                  "proxy-env": False}
        if proxy := proxy_url(self.cfg, "pixiv"):
            common["proxy"] = proxy.replace("socks5://", "socks5h://")
        cookie_file = self.cfg["pixiv"].get("cookie_file")
        if cookie_file:
            common["cookies"] = cookie_file
        pixiv = dict(common)
        pixiv["ugoira"] = "original" if self.cfg["pixiv"]["ugoira_enabled"] else False
        # Bookmark enumeration must stay at one record per bookmarked novel.
        # Embedded illustrations are only expanded during the actual download.
        novel = {**common, "full-series": False,
                 "embeds": self.cfg["pixiv"]["novel_embeds"] if destination else False,
                 "covers": False}
        if destination:
            for section in (pixiv, novel):
                section.update({"base-directory": str(destination), "directory": [],
                                "filename": "{num:04}.{extension}"})
        payload = {"extractor": {"pixiv": pixiv, "pixiv-novel": novel},
                   "output": {"progress": False}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", dir=self.cfg["state_dir"], delete=False) as stream:
            json.dump(payload, stream); name = stream.name
        try:
            yield name
        finally:
            Path(name).unlink(missing_ok=True)

    def _events(self, url):
        with self.config_file() as config, tempfile.TemporaryFile() as output:
            command([sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config, "-j", url],
                    self.cfg["command_timeout_seconds"], output, warnings_are_errors=False)
            output.seek(0)
            try:
                events = json.load(output)
            except ValueError:
                raise SyncError("invalid_export") from None
        errors = [event[-1] for event in events if isinstance(event, list) and event and event[0] == -1]
        usable = [event for event in events if isinstance(event, list) and event and event[0] in (1, 2, 3)
                  and isinstance(event[-1], dict) and str(event[-1].get("id") or "").isdigit()]
        # Deleted and My-Pixiv-only bookmarks appear as per-work errors while
        # pagination itself completes.  They are outside the interface-visible
        # download set and must not prevent a baseline from committing.
        if errors and not usable:
            names = {str(error.get("error", "")) for error in errors if isinstance(error, dict)}
            if names & {"AuthenticationError", "AuthorizationError"}:
                raise SyncError("auth_required")
            raise SyncError("scan_incomplete")
        return events

    def scan(self, source, cursor=0, start=None):
        uid = self._uid()
        novel = "novel" in source
        private = source.endswith("private")
        kind = "novels" if novel else "artworks"
        visibility = "hide" if private else "show"
        url = f"https://www.pixiv.net/users/{uid}/bookmarks/{kind}?rest={visibility}"
        records = {}
        for event in self._events(url):
            if not isinstance(event, list) or not event or event[0] not in (1, 2, 3):
                continue
            meta = event[-1]
            if not isinstance(meta, dict) or not str(meta.get("id") or "").isdigit():
                continue
            work_id = str(meta["id"])
            work_type = "novel" if novel else str(meta.get("type") or "illust")
            if work_type == "ugoira" and not self.cfg["pixiv"]["ugoira_enabled"]:
                continue
            item_id = ("novel:" if novel else "art:") + work_id
            user = meta.get("user") or {}
            author = str(user.get("name") or user.get("account") or "作者未知")
            title = str(meta.get("title") or work_id)
            series = _series_title(meta)
            count = int(meta.get("count") or 1)
            work_url = (f"https://www.pixiv.net/novel/show.php?id={work_id}" if novel
                        else f"https://www.pixiv.net/artworks/{work_id}")
            records[item_id] = {
                "id": item_id, "text": "", "assets": [], "bundle": True,
                "locator": {"url": work_url, "work_id": work_id, "work_type": work_type,
                            "author": author, "title": title, "series": series, "count": count,
                            "naming": {"group": author, "date": ""}},
            }
        return list(records.values()), None

    @staticmethod
    def _comicinfo(meta, count, url):
        root = ET.Element("ComicInfo")
        user = meta.get("user") or {}
        values = {
            "Series": _series_title(meta), "Title": meta.get("title"),
            "Writer": user.get("name") or user.get("account"), "PageCount": count,
            "Web": url,
        }
        raw_date = meta.get("create_date")
        try:
            date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            values.update({"Year": date.year, "Month": date.month, "Day": date.day})
        except (TypeError, ValueError):
            pass
        for key, value in values.items():
            if value not in (None, ""):
                ET.SubElement(root, key).text = str(value)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _stem(self, item, locator):
        parts = [component(locator.get("author") or "作者未知", 56)]
        if locator.get("series"):
            parts.append(component(locator["series"], 56))
        parts.extend((component(locator.get("title") or locator["work_id"], 80), locator["work_id"]))
        proposed = "_".join(part for part in parts if part)
        return self.store.pixiv_stem(item["account"], item["item_id"], proposed)

    def download_bundle(self, item, staging):
        locator = json.loads(item["locator"]); url = locator["url"]
        work_type = locator["work_type"]
        if work_type == "ugoira" and not self.cfg["pixiv"]["ugoira_enabled"]:
            raise SyncError("ugoira_disabled")
        events = self._events(url)
        file_events = [event for event in events if isinstance(event, list) and event and event[0] == 3]
        metas = [event[-1] for event in events if isinstance(event, list) and event and event[0] in (1, 2, 3)
                 and isinstance(event[-1], dict)]
        if not file_events or not metas:
            raise SyncError("content_unavailable")
        meta = metas[0]
        with self.config_file(staging) as config:
            command([sys.executable, "-m", "gallery_dl", "--config-ignore", "-c", config, url],
                    self.cfg["command_timeout_seconds"], warnings_are_errors=True)
        files = sorted(path for path in staging.rglob("*") if path.is_file() and not path.name.endswith(".part"))
        stem = self._stem(item, locator)
        if work_type == "novel":
            texts = [path for path in files if path.suffix.lower() == ".txt"]
            if len(texts) != 1 or not texts[0].read_text(errors="ignore").strip():
                raise SyncError("invalid_content")
            output = Path(self.cfg["pixiv"]["novel_dir"]); output.mkdir(parents=True, exist_ok=True)
            ordered = [texts[0], *(path for path in files if path != texts[0])]
            finals = []
            for index, path in enumerate(ordered):
                name = stem + ("" if index == 0 else f"_p{index:03d}") + path.suffix.lower()
                final = output / name; os.replace(path, final); finals.append(final)
            shutil.rmtree(staging, ignore_errors=True)
            return finals
        if work_type == "ugoira":
            output = Path(self.cfg["pixiv"]["picture_dir"]) / "ugoira"; output.mkdir(parents=True, exist_ok=True)
            finals = []
            for index, path in enumerate(files, 1):
                if path.suffix.lower() == ".zip":
                    with zipfile.ZipFile(path) as archive:
                        if archive.testzip(): raise SyncError("download_invalid_file")
                elif not _valid_media(path):
                    raise SyncError("download_invalid_file")
                final = output / f"{stem}_p{index:03d}{path.suffix.lower()}"
                os.replace(path, final); finals.append(final)
            shutil.rmtree(staging, ignore_errors=True)
            return finals
        images = [path for path in files if _valid_media(path)]
        expected = int(meta.get("count") or locator.get("count") or len(file_events))
        if len(images) != expected or expected != len(file_events):
            raise SyncError("incomplete_gallery")
        output = Path(self.cfg["pixiv"]["picture_dir"]); output.mkdir(parents=True, exist_ok=True)
        if expected < 8:
            finals = []
            for page, image in enumerate(images, 1):
                final = output / f"{stem}_p{page:03d}{image.suffix.lower()}"
                os.replace(image, final); finals.append(final)
            shutil.rmtree(staging, ignore_errors=True)
            return finals
        temp = staging / (stem + ".zip.tmp")
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for page, image in enumerate(images, 1):
                archive.write(image, f"{page:04d}{image.suffix.lower()}")
            archive.writestr("ComicInfo.xml", self._comicinfo(meta, expected, url))
        with zipfile.ZipFile(temp) as archive:
            if archive.testzip() or len(archive.namelist()) != expected + 1:
                raise SyncError("zip_validation_failed")
        final = output / (stem + ".zip"); os.replace(temp, final)
        shutil.rmtree(staging, ignore_errors=True)
        return [final]


class WallabagAdapter:
    def __init__(self, cfg, store=None):
        self.cfg, self.store = cfg, store
        self._access_token = None
        self._expires_at = 0

    def _credentials(self):
        try:
            data = json.loads(Path(self.cfg["wallabag"]["credentials_file"]).read_text())
        except (OSError, ValueError):
            raise SyncError("auth_required") from None
        return data

    def _session(self):
        session = requests.Session(); session.trust_env = False
        if proxy := proxy_url(self.cfg, "wallabag"):
            proxy = proxy.replace("socks5://", "socks5h://")
            session.proxies.update({"http": proxy, "https": proxy})
        return session

    def _token(self):
        if self._access_token and self._expires_at > time.time() + 60:
            return self._access_token
        credentials = self._credentials()
        if credentials.get("access_token"):
            self._access_token = credentials["access_token"]
            self._expires_at = time.time() + 86400
            return self._access_token
        required = ("client_id", "client_secret", "username", "password")
        if any(not credentials.get(key) for key in required):
            raise SyncError("auth_required")
        try:
            response = self._session().post(
                self.cfg["wallabag"]["base_url"].rstrip("/") + "/oauth/v2/token",
                data={"grant_type": "password", **{key: credentials[key] for key in required}}, timeout=30)
        except requests.RequestException:
            raise SyncError("network_failure") from None
        if response.status_code in (401, 403):
            raise SyncError("auth_required")
        if not response.ok:
            raise SyncError("network_failure")
        try:
            payload = response.json(); self._access_token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in") or 3600)
        except (ValueError, KeyError, TypeError):
            raise SyncError("auth_required") from None
        return self._access_token

    def _get(self, path, **kwargs):
        headers = {"Authorization": "Bearer " + self._token()}
        timeout = kwargs.pop("timeout", 120)
        try:
            response = self._session().get(self.cfg["wallabag"]["base_url"].rstrip("/") + path,
                                           headers=headers, timeout=timeout, **kwargs)
        except requests.RequestException:
            raise SyncError("network_failure") from None
        if response.status_code in (401, 403):
            self._access_token = None
            raise SyncError("auth_required")
        if response.status_code == 429:
            raise SyncError("rate_limited")
        if not response.ok:
            raise SyncError("network_failure")
        return response

    def scan(self, source, cursor=0, start=None):
        page, records = 1, []
        while True:
            params = {"page": page, "perPage": self.cfg["wallabag"]["per_page"],
                      "sort": "updated", "order": "asc", "detail": "full"}
            if self.cfg["wallabag"]["tags"]:
                params["tags"] = ",".join(self.cfg["wallabag"]["tags"])
            try:
                payload = self._get("/api/entries.json", params=params).json()
            except ValueError:
                raise SyncError("invalid_export") from None
            entries = (payload.get("_embedded") or {}).get("items") or []
            for entry in entries:
                entry_id = str(entry.get("id") or "")
                if not entry_id.isdigit():
                    raise SyncError("invalid_export")
                text, images = _html_summary(str(entry.get("content") or ""))
                normalized = re.sub(r"\s+", " ", text).strip()
                normalized_html = re.sub(r"\s+", " ", str(entry.get("content") or "")).strip()
                fingerprint = hashlib.sha256(normalized_html.encode()).hexdigest()
                html = str(entry.get("content") or "")
                password_form = bool(re.search(
                    r"<form\b[^>]*>.*?<input\b[^>]*type\s*=\s*['\"]?password\b",
                    html, flags=re.IGNORECASE | re.DOTALL))
                suspicious = len(normalized) < self.cfg["wallabag"]["min_content_chars"] or password_form
                records.append({"id": entry_id, "text": "", "assets": [], "bundle": True,
                                "locator": {"title": str(entry.get("title") or entry_id),
                                            "url": str(entry.get("url") or ""),
                                            "updated_at": str(entry.get("updated_at") or ""),
                                            "fingerprint": fingerprint, "content_chars": len(normalized),
                                            "image_count": len(images), "invalid_content": suspicious,
                                            "naming": {"group": "wallabag", "date": ""}}})
            pages = int(payload.get("pages") or 1)
            if page >= pages:
                break
            if not entries:
                raise SyncError("scan_incomplete")
            page += 1
        return records, None

    def identity(self):
        try:
            payload = self._get("/api/user.json").json()
            identity = str(payload.get("id") or payload.get("username") or "")
        except ValueError:
            raise SyncError("invalid_export") from None
        if not identity:
            raise SyncError("auth_required")
        return identity

    @staticmethod
    def _validate_epub(path, min_chars, expected_images):
        try:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip():
                    raise SyncError("epub_invalid")
                names = set(archive.namelist())
                if archive.read("mimetype").strip() != b"application/epub+zip":
                    raise SyncError("epub_invalid")
                total_text, refs = [], []
                for name in names:
                    if name.lower().endswith((".html", ".xhtml", ".htm")):
                        parser = _TextParser(); parser.feed(archive.read(name).decode("utf-8", "ignore"))
                        total_text.extend(parser.text)
                        for ref in parser.images:
                            refs.append((name, ref))
                if len(" ".join(total_text)) < min_chars:
                    raise SyncError("invalid_content")
                incomplete = False
                for document, ref in refs:
                    parsed = urlparse(ref)
                    if parsed.scheme in ("http", "https"):
                        incomplete = True; continue
                    target = posixpath.normpath(
                        str(PurePosixPath(document).parent.joinpath(parsed.path)))
                    if target not in names:
                        incomplete = True
                packaged_images = sum(name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"))
                                      for name in names)
                if expected_images and not packaged_images:
                    incomplete = True
                return "incomplete" if incomplete else "complete"
        except zipfile.BadZipFile:
            raise SyncError("epub_invalid") from None

    def _fallback_epub(self, item, destination):
        """Create a readable text EPUB when wallabag's PHPePub export stalls."""
        try:
            entry = self._get(f"/api/entries/{item['item_id']}.json", params={"detail": "full"}).json()
        except ValueError:
            raise SyncError("invalid_export") from None
        text, _ = _html_summary(str(entry.get("content") or ""))
        if len(text) < self.cfg["wallabag"]["min_content_chars"]:
            raise SyncError("invalid_content")
        title = str(entry.get("title") or item["item_id"])
        source = str(entry.get("url") or "")
        paragraphs = "".join(f"<p>{html.escape(part)}</p>" for part in text.split("\n") if part.strip())
        xhtml = ("<?xml version='1.0' encoding='utf-8'?>"
                 "<html xmlns='http://www.w3.org/1999/xhtml'><head>"
                 f"<title>{html.escape(title)}</title></head><body><h1>{html.escape(title)}</h1>"
                 f"<p><a href='{html.escape(source, quote=True)}'>{html.escape(source)}</a></p>"
                 f"{paragraphs}</body></html>")
        container = ("<?xml version='1.0'?>"
                     "<container version='1.0' xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
                     "<rootfiles><rootfile full-path='OEBPS/content.opf' "
                     "media-type='application/oebps-package+xml'/></rootfiles></container>")
        opf = ("<?xml version='1.0' encoding='utf-8'?>"
               "<package xmlns='http://www.idpf.org/2007/opf' unique-identifier='id' version='2.0'>"
               "<metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>"
               f"<dc:identifier id='id'>wallabag-{item['item_id']}</dc:identifier>"
               f"<dc:title>{html.escape(title)}</dc:title><dc:language>zh</dc:language></metadata>"
               "<manifest><item id='content' href='content.xhtml' media-type='application/xhtml+xml'/>"
               "<item id='ncx' href='toc.ncx' media-type='application/x-dtbncx+xml'/></manifest>"
               "<spine toc='ncx'><itemref idref='content'/></spine></package>")
        ncx = ("<?xml version='1.0' encoding='utf-8'?>"
               "<ncx xmlns='http://www.daisy.org/z3986/2005/ncx/' version='2005-1'>"
               f"<head><meta name='dtb:uid' content='wallabag-{item['item_id']}'/></head>"
               f"<docTitle><text>{html.escape(title)}</text></docTitle><navMap>"
               "<navPoint id='n1' playOrder='1'><navLabel><text>正文</text></navLabel>"
               "<content src='content.xhtml'/></navPoint></navMap></ncx>")
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            archive.writestr("META-INF/container.xml", container)
            archive.writestr("OEBPS/content.xhtml", xhtml)
            archive.writestr("OEBPS/content.opf", opf)
            archive.writestr("OEBPS/toc.ncx", ncx)

    def download_bundle(self, item, staging):
        locator = json.loads(item["locator"])
        if locator.get("invalid_content"):
            raise SyncError("invalid_content")
        output = Path(self.cfg["wallabag"]["output_dir"]); output.mkdir(parents=True, exist_ok=True)
        proposed = component(locator.get("title") or item["item_id"], 180) + f"_[{item['item_id']}].epub"
        filename = self.store.wallabag_path(item["account"], item["item_id"], proposed)
        partial = staging / "entry.epub.part"
        try:
            response = self._get(f"/api/entries/{item['item_id']}/export.epub", stream=True,
                                 timeout=self.cfg["wallabag"]["export_timeout_seconds"])
            try:
                with partial.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            stream.write(chunk)
                    stream.flush(); os.fsync(stream.fileno())
            finally:
                response.close()
        except SyncError as exc:
            if exc.code != "network_failure":
                raise
            self._fallback_epub(item, partial)
        attachment_status = self._validate_epub(
            partial, self.cfg["wallabag"]["min_content_chars"], int(locator.get("image_count") or 0))
        final = output / filename
        os.replace(partial, final)
        self.store.wallabag_export_result(item["account"], item["item_id"], locator["fingerprint"], attachment_status)
        shutil.rmtree(staging, ignore_errors=True)
        return [final]
