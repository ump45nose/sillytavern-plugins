import logging
import os
from pathlib import Path
import threading
import time
import hashlib
import shutil

from . import cookies
from .adapters import TelegramAdapter, XAdapter
from .adapters_ext import EhAdapter, XhsAdapter
from .adapters_pixiv_wallabag import PixivAdapter, WallabagAdapter
from .common import SyncError, atomic_write
from .config import SOURCES, start_timestamp, telegram_accounts
from .store import Store
from .layout import paths
from .journal import append_entry


log = logging.getLogger("favsync")


class Engine:
    def __init__(self, cfg, adapters=None):
        self.cfg = cfg
        self.store = Store(cfg["state_dir"])
        self.adapters = adapters or {"telegram": TelegramAdapter(cfg), "x": XAdapter(cfg)}
        self.adapters.setdefault("eh", EhAdapter(cfg, self.store))
        self.adapters.setdefault("xhs", XhsAdapter(cfg, self.store))
        self.adapters.setdefault("pixiv", PixivAdapter(cfg, self.store))
        self.adapters.setdefault("wallabag", WallabagAdapter(cfg, self.store))
        self.attempted = set()

    def sources(self):
        for profile in telegram_accounts(self.cfg):
            adapter = self.adapters["telegram"] if profile["account"] == self.cfg["telegram"]["account"] else TelegramAdapter({**self.cfg, "telegram": profile})
            yield "telegram", profile, adapter
        for name in ("x_bookmarks", "x_likes"):
            yield name, self.cfg[name], self.adapters["x"]
        yield "eh_favorites", self.cfg["eh_favorites"], self.adapters["eh"]
        for name in ("xhs_favorites", "xhs_likes"):
            yield name, self.cfg[name], self.adapters["xhs"]
        for name in ("pixiv_art_public", "pixiv_art_private", "pixiv_novel_public", "pixiv_novel_private"):
            yield name, self.cfg[name], self.adapters["pixiv"]
        yield "wallabag_entries", self.cfg["wallabag_entries"], self.adapters["wallabag"]

    def cookie_sync(self):
        if not self.cfg["cookiecloud"]["enabled"]:
            return True
        started = time.time()
        # Dedicated connection: the daemon cookie thread never shares SQLite objects.
        db = Store(self.cfg["state_dir"])
        try:
            results = cookies.sync(self.cfg)
            for platform, status in results.items():
                db.setting("cookiecloud_status:" + platform, status)
            complete = all(status == "ok" for status in results.values())
            db.setting("cookiecloud_status", "ok" if complete else "partial")
            db.setting("cookiecloud_last_success", str(time.time()))
            db.record_execution("cookiecloud", started, complete)
            return complete
        except SyncError as exc:
            db.setting("cookiecloud_status", exc.code)
            db.record_execution("cookiecloud", started, False)
            log.warning("cookiecloud: %s (previous cookie retained)", exc.code)
            return False
        except Exception:
            db.record_execution("cookiecloud", started, False)
            raise
        finally:
            db.close()

    def cookie_loop(self, stop):
        while not stop.wait(self.cfg["cookiecloud"]["interval_seconds"]):
            self.cookie_sync()

    def check_x(self, account):
        if float(self.store.setting("x_rate_until") or 0) > time.time():
            raise SyncError("rate_limited")
        token = cookies.identity(self.cfg)
        if token:
            key = "x_identity:" + account
            previous = self.store.setting(key)
            if previous and previous != token:
                raise SyncError("x_account_changed")
            self.store.setting(key, token)
        blocked = self.store.setting("x_blocked_cookie")
        if blocked and blocked == cookies.fingerprint(self.cfg):
            raise SyncError("auth_required")

    def telegram_session_digest(self, account):
        try:
            return hashlib.sha256((Path(self.cfg["state_dir"]) / "tdl" / account).read_bytes()).hexdigest()
        except FileNotFoundError:
            return "missing"

    def cycle(self):
        started = time.time()
        try:
            success = self._cycle()
        except Exception:
            self.store.record_execution("content", started, False)
            raise
        self.store.record_execution("content", started, success)
        return success

    def _cycle(self):
        self.attempted.clear()
        failures = False
        for source, section, adapter in self.sources():
            account = section["account"]
            state = self.store.source(source, account)
            if not section["enabled"]:
                self.store.update(source, account, scan_status="disabled")
                continue
            pixiv_source = source.startswith("pixiv_")
            dated = source in ("telegram", "x_bookmarks") or pixiv_source
            configured_date = (self.cfg["pixiv"].get("start_date", "") if pixiv_source
                               else section.get("start_date", ""))
            start = start_timestamp(configured_date, self.cfg["timezone"]) if dated else None
            if dated and start is None:
                self.store.update(source, account, scan_status="awaiting_start_date", error=None)
                log.info("%s: awaiting_start_date", source)
                continue
            if pixiv_source and time.time() < start:
                self.store.update(source, account, scan_status="awaiting_start_date", error=None)
                log.info("%s: awaiting_start_date", source)
                continue
            x_source = source.startswith("x_") and not source.startswith("xhs_")
            digest = cookies.fingerprint(self.cfg) if x_source else None
            try:
                if x_source:
                    self.check_x(account)
                elif self.store.setting("telegram_blocked_session:" + account) == self.telegram_session_digest(account):
                    raise SyncError("auth_required")
                baseline = ((source in ("x_likes", "eh_favorites") or pixiv_source)
                            and state["baseline_at"] is None)
                self.store.update(source, account, scan_status="initializing_baseline" if baseline else "scanning", error=None)
                # Changing the date rescans historical Telegram messages idempotently.
                cursor = state["cursor"] if state["start_date"] == str(section.get("start_date", "")) else 0
                records, cursor = adapter.scan(source, cursor=cursor, start=start)
                if (source == "eh_favorites" or source.startswith("xhs_") or
                        source.startswith("pixiv_") or source == "wallabag_entries"):
                    platform = ("eh" if source == "eh_favorites" else
                                "xhs" if source.startswith("xhs_") else
                                "pixiv" if source.startswith("pixiv_") else "wallabag")
                    current_identity = adapter.identity()
                    identity_key = f"{platform}_identity:{account}"
                    previous_identity = self.store.setting(identity_key)
                    if previous_identity and previous_identity != current_identity:
                        raise SyncError(f"{platform}_account_changed")
                    self.store.setting(identity_key, current_identity)
                bad_dates = 0
                if source == "x_bookmarks":
                    bad_dates = sum(r["action_time"] is None for r in records)
                    records = [r for r in records if r["action_time"] is not None and r["action_time"] >= start]
                # Bind Saved Messages state to the actual peer ID when there are results.
                if source == "telegram" and getattr(adapter, "account_id", None):
                    peer = adapter.account_id
                    previous = self.store.setting("tg_identity:" + account)
                    if previous and previous != peer:
                        raise SyncError("telegram_account_changed")
                    self.store.setting("tg_identity:" + account, peer)
                if source == "wallabag_entries":
                    self.store.ingest_wallabag(source, account, records)
                else:
                    self.store.ingest(source, account, records, baseline=baseline,
                                      cursor=cursor, start_date=str(configured_date))
                if bad_dates:
                    self.store.update(source, account, scan_status="incomplete", error="bookmark_time_unknown")
                    log.warning("%s: %d items deferred (bookmark_time_unknown)", source, bad_dates)
                    failures = True
                outcome = "baseline_complete" if baseline else ("scan_incomplete" if bad_dates else "scan_complete")
                log.info("%s: %s, discovered=%d", source, outcome, len(records))
            except SyncError as exc:
                failures = True
                self.store.update(source, account, scan_status="incomplete", error=exc.code)
                log.warning("%s: %s", source, exc.code)
                if x_source and exc.code == "auth_required":
                    self.store.setting("x_blocked_cookie", digest)
                elif source == "telegram" and exc.code == "auth_required":
                    self.store.setting("telegram_blocked_session:" + account, self.telegram_session_digest(account))
                if x_source and exc.code == "rate_limited" and float(self.store.setting("x_rate_until") or 0) <= time.time():
                    self.store.setting("x_rate_until", str(time.time() + max(900, self.cfg["interval_seconds"])))
                if exc.code in ("auth_required", "rate_limited", "x_account_changed", "eh_account_changed",
                                "xhs_account_changed", "pixiv_account_changed", "wallabag_account_changed",
                                "telegram_account_changed", "telegram_session_in_use"):
                    continue
            except Exception as exc:
                # Avoid tracebacks/exception messages containing third-party payloads.
                failures = True
                self.store.update(source, account, scan_status="incomplete", error="internal_error")
                log.error("%s: internal_error (%s)", source, type(exc).__name__)
                continue
            # Existing durable jobs remain retryable even after a failed enumeration.
            try:
                if not self.drain(source, account, adapter):
                    failures = True
            except SyncError as exc:
                failures = True
                self.store.update(source, account, error=exc.code)
                if x_source and exc.code == "auth_required":
                    self.store.setting("x_blocked_cookie", digest)
                elif source == "telegram" and exc.code == "auth_required":
                    self.store.setting("telegram_blocked_session:" + account, self.telegram_session_digest(account))
                if x_source and exc.code == "rate_limited" and float(self.store.setting("x_rate_until") or 0) <= time.time():
                    self.store.setting("x_rate_until", str(time.time() + max(900, self.cfg["interval_seconds"])))
            except OSError:
                failures = True
                self.store.update(source, account, error="filesystem_error")
                log.error("%s: filesystem_error", source)
        return not failures

    def drain(self, source, account, adapter, item_ids=None):
        success = True
        for item in self.store.pending(source, account):
            if item_ids is not None and item['item_id'] not in item_ids:
                continue
            text_path = paths(self.cfg, item)
            folder = text_path.parent
            folder.mkdir(parents=True, exist_ok=True)
            staging = folder / f".partial-{account}-{item['item_id']}"
            staging.mkdir(exist_ok=True)
            if item["bundle_status"] in ("pending", "failed", "paused_low_disk"):
                if not self.disk_ready():
                    self.store.bundle_result(item, "paused_low_disk")
                    self.store.update(source, account, scan_status="paused_low_disk", error="low_disk")
                    success = False
                    continue
                try:
                    adapter.download_bundle(item, staging)
                    self.store.bundle_result(item)
                    log.info("%s: item=%s bundle downloaded", source, item["item_id"])
                except SyncError as exc:
                    self.store.bundle_result(item, exc.code)
                    success = False
                    log.warning("%s: item=%s %s", source, item["item_id"], exc.code)
                except OSError:
                    self.store.bundle_result(item, "filesystem_error")
                    success = False
                continue
            for asset in self.store.assets(item):
                key = (item["platform"], account, item["item_id"], asset["number"])
                if asset["status"] == "done" or key in self.attempted:
                    continue
                if not self.disk_ready():
                    self.store.update(source, account, scan_status="paused_low_disk", error="low_disk")
                    success = False
                    break
                self.attempted.add(key)
                final = paths(self.cfg, item, asset)
                try:
                    if not final.is_file():
                        download_item = dict(item)
                        if item['platform'] == 'x':
                            download_item['_pending_numbers'] = [a['number'] for a in self.store.assets(item) if a['status'] != 'done']
                        downloaded = adapter.download(download_item, asset, staging)
                        if not downloaded.is_file() or downloaded.stat().st_size == 0:
                            raise SyncError("download_missing_file")
                        with downloaded.open("rb") as f:
                            os.fsync(f.fileno())
                        os.replace(downloaded, final)
                    self.store.asset_result(asset, size=final.stat().st_size)
                    log.info("%s: item=%s asset=%s downloaded", source, item["item_id"], asset["number"])
                except SyncError as exc:
                    self.store.asset_result(asset, error=exc.code)
                    success = False
                    log.warning("%s: item=%s asset=%s %s", source, item["item_id"], asset["number"], exc.code)
                    if exc.code in ("auth_required", "rate_limited"):
                        raise
                except OSError:
                    self.store.asset_result(asset, error="filesystem_error")
                    success = False
            try:
                staging.rmdir()
            except OSError:
                pass
            assets = self.store.assets(item)
            if all(a['status'] == 'done' for a in assets):
                append_entry(self.cfg, item, assets)
                self.store.text_done(item)
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
        stop = threading.Event()
        self.cookie_sync()
        worker = threading.Thread(target=self.cookie_loop, args=(stop,), daemon=True)
        worker.start()
        try:
            while True:
                started = time.monotonic()
                self.cycle()
                stop.wait(max(1, self.cfg["interval_seconds"] - (time.monotonic() - started)))
        finally:
            stop.set()
            worker.join(timeout=2)
