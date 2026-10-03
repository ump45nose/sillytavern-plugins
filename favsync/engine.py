import logging
from pathlib import Path
import threading
import time
import shutil

from . import cookies
from .accounts import ACCOUNT_ERRORS, XHS_FUSE_ERRORS, AccountGuard
from .acquisition import collect_source
from .downloads import drain_queue
from .adapters import TelegramAdapter
from .common import SyncError, process_lock
from .config import telegram_accounts, telegram_config
from .database import migrate
from .sources import SOURCE_SPECS, make_adapter
from .store import Store
from .layout import paths, platform_root
from .journal import write_item_markdown

log = logging.getLogger("favsync")


class Engine:
    def __init__(self, cfg, adapters=None):
        self.cfg = cfg
        migrate(cfg["state_dir"])
        self.store = Store(cfg["state_dir"])
        self.adapters = dict(adapters or {})
        self.guard = AccountGuard(cfg, self.store)
        self.attempted = set()

    def close(self):
        try:
            for adapter in {id(value): value for value in self.adapters.values()}.values():
                if close := getattr(adapter, "close", None):
                    close()
        finally:
            self.store.close()

    def sources(self):
        for spec in SOURCE_SPECS:
            sections = telegram_accounts(self.cfg) if spec.name == "telegram" else [self.cfg[spec.name]]
            for section in sections:
                yield spec, section

    def adapter(self, spec, account):
        key = spec.adapter
        cfg = self.cfg
        if key == "telegram":
            cfg = telegram_config(self.cfg, account)
            if account != self.cfg["telegram"]["account"]:
                key += ":" + account
        if key not in self.adapters:
            self.adapters[key] = (TelegramAdapter(cfg) if spec.adapter == "telegram"
                                  else make_adapter(spec.adapter, cfg, self.store))
        return self.adapters[key]

    def cookie_sync(self):
        if not self.cfg["cookiecloud"]["enabled"]:
            return True
        try:
            with process_lock(self.cfg["state_dir"], name="cookiecloud"):
                return self._cookie_sync()
        except SyncError as exc:
            if exc.code == "worker_already_running":
                return True
            raise

    def _cookie_sync(self):
        started = time.time()
        db = Store(self.cfg["state_dir"])
        try:
            results = cookies.sync(self.cfg)
            for platform, status in results.items():
                db.setting("cookiecloud_status:" + platform, status)
            complete = all(status == "ok" for status in results.values())
            db.setting("cookiecloud_status", "ok" if complete else "partial")
            if complete:
                db.setting("cookiecloud_last_success", str(time.time()))
            db.record_execution("cookiecloud", started, complete)
            return complete
        except SyncError as exc:
            db.setting("cookiecloud_status", exc.code)
            db.record_execution("cookiecloud", started, False)
            log.warning("cookiecloud: %s (previous cookie retained)", exc.code)
            return False
        finally:
            db.close()

    def cookie_loop(self, stop):
        if not self.cfg["cookiecloud"]["enabled"]:
            return
        while not stop.is_set():
            try:
                db = Store(self.cfg["state_dir"], readonly=True)
                try:
                    last = db.last_execution_finished("cookiecloud")
                finally:
                    db.close()
                remaining = (last + self.cfg["cookiecloud"]["interval_seconds"] - time.time()) if last else 0
                if remaining > 0:
                    stop.wait(remaining)
                    continue
                self.cookie_sync()
                # A concurrent manual sync can still be holding the cookie lock.
                stop.wait(1)
            except Exception as exc:
                log.error("cookiecloud: internal_error (%s)", type(exc).__name__)
                stop.wait(60)

    def cycle(self, only_source=None):
        with process_lock(self.cfg["state_dir"]):
            started = time.time()
            kind = "content" if only_source is None else "source:" + only_source
            try:
                success = self._cycle(only_source)
            except Exception:
                self.store.record_execution(kind, started, False)
                raise
            self.store.record_execution(kind, started, success)
            return success

    def _failure(self, spec, account, adapter, code, digest=None):
        self.guard.failed(spec, account, code, digest)
        if hasattr(adapter, "observe"):
            adapter.observe(error=code)
        state = "paused_risk" if spec.adapter == "xhs" and code in XHS_FUSE_ERRORS else "incomplete"
        self.store.update(spec.name, account, scan_status=state, error=code)
        log.warning("%s: %s", spec.name, code)

    def _cycle(self, only_source=None):
        self.attempted.clear()
        self.guard.blocked.clear()
        initialized = set()
        failures = False
        for spec, section in self.sources():
            if only_source and spec.name != only_source:
                continue
            account = section["account"]
            self.store.source(spec.name, account)
            if not section["enabled"]:
                self.store.update(spec.name, account, scan_status="disabled")
                continue
            adapter = None
            digest = cookies.fingerprint(self.cfg) if spec.adapter == "x" else None
            try:
                adapter = self.adapter(spec, account)
                if id(adapter) not in initialized:
                    if hasattr(adapter, "begin_run"):
                        adapter.begin_run()
                    initialized.add(id(adapter))
                if hasattr(adapter, "begin_source"):
                    adapter.begin_source(spec.name, account)
                self.guard.check(spec, account)
                if not self._sync_source(spec, section, adapter, digest):
                    failures = True
            except SyncError as exc:
                failures = True
                self._failure(spec, account, adapter, exc.code, digest)
            except Exception as exc:
                failures = True
                self._failure(spec, account, adapter, "internal_error", digest)
                log.error("%s: internal_error (%s)", spec.name, type(exc).__name__)
        return not failures

    def _sync_source(self, spec, section, adapter, digest):
        source, account = spec.name, section["account"]
        try:
            success = collect_source(self.cfg, self.store, self.guard, spec, section, adapter)
            if success is None:  # Start date not reached or metadata-only source.
                return True
        except SyncError as exc:
            self._failure(spec, account, adapter, exc.code, digest)
            if exc.code in ACCOUNT_ERRORS:
                return False
            success = False
        # Enumeration errors do not discard existing durable work.
        if not self.drain(source, account, adapter):
            success = False
        if spec.markdown and not self.publish_markdown(source, account):
            success = False
        return success

    def drain(self, source, account, adapter, item_ids=None):
        # Keep the established entry point for callers and maintenance tools.
        return drain_queue(self.cfg, self.store, source, account, adapter,
                           attempted=self.attempted, disk_ready=self.disk_ready,
                           item_ids=item_ids)

    def publish_markdown(self, source, account):
        success = True
        for item in self.store.markdown_pending(source, account):
            try:
                if item["platform"] == "xhs":
                    if item["bundle_status"] != "done":
                        continue
                    root = platform_root(self.cfg, "xhs")
                    media = self.store.xhs_media_files(item, root)
                    stem = self.store.xhs_name_stem(item)
                    if not media or not stem:
                        raise OSError("media_missing")
                else:
                    assets = self.store.assets(item)
                    if any(asset["status"] != "done" for asset in assets):
                        continue
                    media = [paths(self.cfg, item, asset) for asset in assets]
                    stem = None
                target = write_item_markdown(self.cfg, item, media, stem=stem)
                self.store.markdown_result(source, account, item["item_id"],
                                           target.name if target else "", "written" if target else "no_text")
            except OSError:
                success = False
                log.warning("%s: item=%s markdown_write_failed", source, item["item_id"])
        return success

    def disk_ready(self):
        target = Path(self.cfg["download_dir"])
        free = shutil.disk_usage(target).free
        paused = self.store.setting("low_disk_paused") == "1"
        limit = self.cfg["storage"]["resume_free_bytes"] if paused else self.cfg["storage"]["min_free_bytes"]
        ready = free >= limit
        self.store.setting("low_disk_paused", "0" if ready else "1")
        self.store.setting("disk_free_bytes", str(free))
        return ready

    def run(self):
        # A scheduler singleton is separate from the short-lived worker lock.
        with process_lock(self.cfg["state_dir"], name="scheduler"):
            stop = threading.Event()
            worker = threading.Thread(target=self.cookie_loop, args=(stop,), daemon=True)
            worker.start()
            try:
                while True:
                    last_content = self.store.last_execution_finished("content")
                    remaining = (last_content + self.cfg["interval_seconds"] - time.time()) if last_content else 0
                    if remaining > 0:
                        log.info("content: next scheduled cycle in %d seconds", int(remaining))
                        stop.wait(remaining)
                        continue
                    try:
                        self.cycle()
                    except SyncError as exc:
                        if exc.code != "worker_already_running":
                            raise
                        log.info("content: another job holds worker lock; retrying in 60 seconds")
                        stop.wait(60)
            finally:
                stop.set()
                worker.join(timeout=2)
