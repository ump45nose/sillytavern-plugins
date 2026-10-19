"""Private credentials and one daily write intent, bound to edition and UID."""
import json
import os
from pathlib import Path
from datetime import date

from common.model import atomic_json
from common.details import number


class WorkBuddyError(Exception):
    def __init__(self, reason, *, status=None, code=None):
        super().__init__(reason)
        self.reason, self.status, self.code = reason, status, code


def durable_json(path, value):
    atomic_json(path, value)
    directory = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read_private(path):
    try:
        path = Path(path)
        if not path.is_absolute() or path.stat().st_mode & 0o077:
            raise WorkBuddyError("private_credentials_permissions")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except WorkBuddyError:
        raise
    except FileNotFoundError:
        raise WorkBuddyError("missing_session") from None
    except (OSError, ValueError, TypeError):
        raise WorkBuddyError("invalid_session") from None


def credential_path(path):
    if not path or not Path(path).is_absolute():
        raise WorkBuddyError("invalid_session_path")
    path = Path(path).resolve()
    root = Path(__file__).resolve().parents[2]
    if root == path or root in path.parents:
        raise WorkBuddyError("credentials_inside_source")
    return path


def validate_session(value, edition):
    if not isinstance(value, dict) or value.get("edition") != edition:
        raise WorkBuddyError("session_edition_mismatch")
    allowed = {"edition", "access_token", "refresh_token", "uid", "enterprise_id", "domain"}
    if set(value) - allowed:
        raise WorkBuddyError("invalid_session")
    for name in allowed - {"edition"}:
        item = value.get(name, "")
        limit = 16384 if name in {"access_token", "refresh_token"} else 256
        if (not isinstance(item, str) or len(item) > limit or
                any(ord(c) < 32 or ord(c) == 127 for c in item)):
            raise WorkBuddyError("invalid_session")
    if not value.get("access_token") or not value.get("uid"):
        raise WorkBuddyError("invalid_session")
    domain = value.get("domain", "").lower()
    if domain and ((edition == "cn" and domain.endswith(".ai")) or
                   (edition == "intl" and domain.endswith(".cn"))):
        raise WorkBuddyError("session_edition_mismatch")
    return dict(value)


class Credentials:
    def __init__(self, path, edition):
        if not path:
            raise WorkBuddyError("missing_session")
        self.path = credential_path(path)
        self.session = validate_session(read_private(self.path), edition)

    def save(self, value):
        value = validate_session(value, self.session["edition"])
        try:
            durable_json(self.path, value)
        except (OSError, ValueError):
            raise WorkBuddyError("credential_write_failed") from None
        self.session = value


class Journal:
    def __init__(self, context, directory, edition, uid):
        self.path = Path(directory) / "daily-intent.json"
        self.value = {"version": 1, "account": context["account"], "uid": uid,
                      "edition": edition, "date": context["business_date"], "status": "unknown"}
        if edition == "cn":
            self.value["reward"] = None
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(4097)
            old = json.loads(raw)
            if (len(raw) > 4096 or not isinstance(old, dict) or set(old) != set(self.value)
                    or old["version"] != 1 or old["account"] != context["account"]
                    or old["uid"] != uid or old["edition"] != edition
                    or old["status"] not in {"unknown", "pending", "complete"}):
                raise ValueError()
            if edition == "cn" and old["reward"] is not None and (
                    number(old["reward"]) is None or number(old["reward"]) < 0):
                raise ValueError()
            date.fromisoformat(old["date"])
            if old["date"] > context["business_date"]:
                raise ValueError()
            if old["date"] == context["business_date"]:
                self.value = old
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            raise WorkBuddyError("invalid_action_state") from None

    @property
    def status(self):
        return self.value["status"]

    def set(self, status, reward=None):
        value = {**self.value, "status": status}
        if self.value["edition"] == "cn" and reward is not None:
            value["reward"] = reward
        if value == self.value and self.path.exists():
            return
        try:
            durable_json(self.path, value)
        except (OSError, ValueError):
            raise WorkBuddyError("action_state_write_failed") from None
        self.value = value
