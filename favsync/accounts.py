"""Account-level pause and identity rules, independent of job scheduling."""
import hashlib
from pathlib import Path
import time

from . import cookies
from .common import SyncError

XHS_FUSE_ERRORS = {"auth_required", "verification_required", "rate_limited",
                   "risk_control_suspected", "xhs_account_changed"}
ACCOUNT_ERRORS = XHS_FUSE_ERRORS | {
    "x_account_changed", "eh_account_changed", "pixiv_account_changed",
    "wallabag_account_changed", "telegram_account_changed", "bili_account_changed",
    "telegram_session_in_use",
}


class AccountGuard:
    def __init__(self, cfg, store):
        self.cfg, self.store = cfg, store
        self.blocked = {}

    def session_digest(self, account):
        try:
            return hashlib.sha256((Path(self.cfg["state_dir"]) / "tdl" / account).read_bytes()).hexdigest()
        except FileNotFoundError:
            return "missing"

    def check(self, spec, account):
        if reason := self.blocked.get((spec.adapter, account)):
            raise SyncError(reason)
        if spec.adapter == "x":
            if float(self.store.setting("x_rate_until") or 0) > time.time():
                raise SyncError("rate_limited")
            self._identity("x_identity:" + account, cookies.identity(self.cfg), "x_account_changed")
            blocked = self.store.setting("x_blocked_cookie")
            if blocked and blocked == cookies.fingerprint(self.cfg):
                raise SyncError("auth_required")
        elif spec.adapter == "telegram":
            if self.store.setting("telegram_blocked_session:" + account) == self.session_digest(account):
                raise SyncError("auth_required")
        elif spec.adapter == "xhs" and (fuse := self.store.xhs_fuse(account)):
            raise SyncError(fuse["reason"])

    def _identity(self, key, identity, error):
        if identity:
            previous = self.store.setting(key)
            if previous and previous != identity:
                raise SyncError(error)
            self.store.setting(key, identity)

    def validate_scan(self, spec, account, adapter):
        if spec.adapter in ("eh", "xhs", "pixiv", "wallabag"):
            self._identity(f"{spec.adapter}_identity:{account}", adapter.identity(),
                           spec.adapter + "_account_changed")
        elif spec.adapter == "telegram" and getattr(adapter, "account_id", None):
            key = "tg_identity:" + ("" if spec.name == "telegram" else spec.name + ":") + account
            self._identity(key, adapter.account_id, "telegram_account_changed")

    def failed(self, spec, account, error, cookie_digest=None):
        if error in ACCOUNT_ERRORS:
            self.blocked[(spec.adapter, account)] = error
        if spec.adapter == "xhs" and error in XHS_FUSE_ERRORS:
            # Keep the first incident timestamp while the fuse is already set.
            if not self.store.xhs_fuse(account):
                self.store.set_xhs_fuse(account, error)
        if spec.adapter == "x" and error == "auth_required":
            self.store.setting("x_blocked_cookie", cookie_digest or cookies.fingerprint(self.cfg))
        elif spec.adapter == "telegram" and error == "auth_required":
            self.store.setting("telegram_blocked_session:" + account, self.session_digest(account))
        if spec.adapter == "x" and error == "rate_limited" and float(self.store.setting("x_rate_until") or 0) <= time.time():
            self.store.setting("x_rate_until", str(time.time() + max(900, self.cfg["interval_seconds"])))
