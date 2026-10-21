"""One-pass EH downloads with original-byte checks and progress-based timeouts."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import tempfile
import time

from gallery_dl import config, exception, job, output
from gallery_dl.extractor.exhentai import ExhentaiGalleryExtractor

from .common import SyncError, classify
from .media import valid_media

log = logging.getLogger("favsync")
HASH = re.compile(r"f_shash=([0-9a-f]{40})")


class OriginalExtractor(ExhentaiGalleryExtractor):
    """Keep the site's original hash beside each image, including direct originals."""
    original_sha1 = None

    def image_from_page(self, page):
        url, data = super().image_from_page(page)
        match = HASH.search(page)
        data["_original_sha1"] = match[1] if match else None
        return url, data

    def request_json(self, *args, **kwargs):
        payload = super().request_json(*args, **kwargs)
        match = HASH.search(payload.get("i6", ""))
        self.original_sha1 = match[1] if match else None
        return payload

    def images_from_api(self):
        for url, data in super().images_from_api():
            data["_original_sha1"] = self.original_sha1
            yield url, data


def emit(kind, payload=None):
    print(json.dumps([kind, payload], default=str), flush=True)


class OriginalDownloadJob(job.DownloadJob):
    error = None

    def handle_directory(self, metadata):
        super().handle_directory(metadata)
        keys = ("gid", "title", "title_jpn", "date", "eh_category", "language",
                "lang", "filecount", "rating", "tags")
        emit("meta", {key: metadata[key] for key in keys if key in metadata})

    def fail(self, code):
        self.error = code
        raise exception.AbortExtraction(code)

    def handle_url(self, url, metadata):
        expected = metadata.get("_original_sha1")
        if not self.extractor.original or ("/fullimg" not in url and not expected):
            self.fail("original_unavailable")
        super().handle_url(url, metadata)
        if self.status:
            raise exception.AbortExtraction("Page download failed")
        path = Path(self.pathfmt.realpath)
        if path.is_symlink() or not path.is_file() or not valid_media(path):
            self.fail("incomplete_gallery")
        if expected:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha1").hexdigest()
            if digest != expected:
                self.fail("original_unavailable")
        emit("page", metadata["num"])


def download_gallery(config_path, url, timeout):
    """Wait for completed pages, rather than imposing one deadline on the whole book."""
    argv = [sys.executable, "-m", "favsync.eh_download", "-c", config_path, url]
    metadata, page, complete = None, 0, False
    with tempfile.TemporaryFile() as errors:
        try:
            process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=errors)
        except OSError:
            raise SyncError("tool_unavailable") from None
        try:
            deadline = time.monotonic() + timeout
            pending = b""
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if not selector.select(max(0, deadline - time.monotonic())):
                        raise SyncError("command_timeout")
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    pending += chunk
                    while b"\n" in pending:
                        line, pending = pending.split(b"\n", 1)
                        try:
                            kind, payload = json.loads(line)
                        except (ValueError, TypeError):
                            raise SyncError("invalid_export") from None
                        if kind == "error":
                            raise SyncError(payload)
                        if kind == "meta":
                            metadata = payload
                        elif kind == "page":
                            if payload != page + 1:
                                raise SyncError("incomplete_gallery")
                            page = payload
                            if page == 1 or page % 50 == 0:
                                log.info("eh: gallery=%s download pages=%s/%s",
                                         metadata.get("gid", ""), page, metadata["filecount"])
                        elif kind == "done":
                            complete = True
                        else:
                            raise SyncError("invalid_export")
                        deadline = time.monotonic() + timeout
            try:
                status = process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                raise SyncError("command_timeout") from None
            errors.seek(0)
            diagnostics = errors.read().decode("utf-8", "replace")
            warnings = [line for line in diagnostics.splitlines() if "[warning]" in line.lower()]
            if (status or "[error]" in diagnostics.lower()
                    or any(not line.startswith("[downloader.http][warning]") for line in warnings)):
                raise SyncError(classify(diagnostics))
            if pending or not complete or not metadata or page != int(metadata["filecount"]):
                raise SyncError("incomplete_gallery")
            if warnings:
                log.info("eh: gallery=%s recovered transfer warnings=%d",
                         metadata.get("gid", ""), len(warnings))
            return metadata
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-c", required=True)
    parser.add_argument("url")
    args = parser.parse_args(argv)
    output.initialize_logging(logging.WARNING)
    config.clear()
    config.load((args.c,), strict=True)
    task = OriginalDownloadJob(OriginalExtractor.from_url(args.url))
    task.out = output.NullOutput()
    status = task.run()
    if task.error:
        emit("error", task.error)
    elif status & 128:
        emit("error", "filesystem_error")
    elif not status:
        emit("done")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
