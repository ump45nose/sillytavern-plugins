"""Durable queue execution; source enumeration owns no download side effects."""
import logging
import shutil

from .accounts import ACCOUNT_ERRORS
from .common import SyncError, TERMINAL_ASSET_STATES
from .layout import paths
from .publication import accepted_size, publish_file

log = logging.getLogger("favsync")


def drain_queue(cfg, store, source, account, adapter, *, attempted, disk_ready, item_ids=None):
    success = True
    for item in store.pending(source, account):
        if item_ids is not None and item['item_id'] not in item_ids:
            continue
        text_path = paths(cfg, item)
        folder = text_path.parent
        folder.mkdir(parents=True, exist_ok=True)
        staging = folder / f".partial-{account}-{item['item_id']}"
        staging.mkdir(exist_ok=True)
        if item["bundle_status"] in ("pending", "failed", "paused_low_disk"):
            if hasattr(adapter, "take_bundle_slot") and not adapter.take_bundle_slot():
                log.info("%s: bundle request budget exhausted; remaining items deferred", source)
                break
            if not disk_ready():
                store.bundle_result(item, "paused_low_disk")
                store.update(source, account, scan_status="paused_low_disk", error="low_disk")
                success = False
                continue
            try:
                artifacts = adapter.download_bundle(item, staging)
                if not artifacts:
                    raise SyncError("download_missing_file")
                for artifact in artifacts:
                    accepted_size(artifact)
                store.bundle_result(item)
                log.info("%s: item=%s bundle downloaded", source, item["item_id"])
            except SyncError as exc:
                if exc.code == "deferred_request_budget":
                    log.info("%s: detail request budget exhausted; remaining items deferred", source)
                    break
                if item["platform"] == "xhs" and hasattr(adapter, "observe"):
                    adapter.observe(error=exc.code)
                store.bundle_result(item, exc.code)
                if item["platform"] == "wallabag" and exc.code == "invalid_content":
                    shutil.rmtree(staging, ignore_errors=True)
                    log.info("%s: item=%s skipped_invalid", source, item["item_id"])
                    continue
                success = False
                log.warning("%s: item=%s %s", source, item["item_id"], exc.code)
                if exc.code in ACCOUNT_ERRORS:
                    raise
            except OSError:
                store.bundle_result(item, "filesystem_error")
                success = False
            except Exception:
                store.bundle_result(item, "internal_error")
                raise
            continue
        for asset in store.assets(item):
            key = (item["platform"], account, item["item_id"], asset["number"])
            if asset["status"] in TERMINAL_ASSET_STATES or key in attempted:
                continue
            if not disk_ready():
                store.update(source, account, scan_status="paused_low_disk", error="low_disk")
                success = False
                break
            attempted.add(key)
            final = paths(cfg, item, asset)
            try:
                if final.exists() or final.is_symlink():
                    if asset["error"] == "destination_exists":
                        # A collision discovered during publication is not
                        # crash recovery evidence on the next run either.
                        raise SyncError("destination_exists")
                    size = accepted_size(final, error="existing_file_invalid")
                else:
                    download_item = dict(item)
                    if item['platform'] == 'x':
                        download_item['_pending_numbers'] = [a['number'] for a in store.assets(item) if a['status'] not in TERMINAL_ASSET_STATES]
                    downloaded = adapter.download(download_item, asset, staging)
                    size = publish_file(downloaded, final)
                store.asset_result(asset, size=size)
                log.info("%s: item=%s asset=%s downloaded", source, item["item_id"], asset["number"])
            except SyncError as exc:
                store.asset_result(asset, error=exc.code)
                if item["platform"] == "x" and exc.code == "content_unavailable":
                    log.info("%s: item=%s asset=%s skipped_unavailable", source, item["item_id"], asset["number"])
                    continue
                success = False
                log.warning("%s: item=%s asset=%s %s", source, item["item_id"], asset["number"], exc.code)
                if exc.code in ACCOUNT_ERRORS:
                    raise
            except OSError:
                store.asset_result(asset, error="filesystem_error")
                success = False
        try:
            staging.rmdir()
        except OSError:
            pass
        assets = store.assets(item)
        if all(a['status'] in TERMINAL_ASSET_STATES for a in assets):
            store.text_done(item)
    return success
