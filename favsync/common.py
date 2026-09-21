from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import subprocess
import tempfile


class SyncError(Exception):
    """Only public, non-sensitive error codes leave subprocess boundaries."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def classify(text):
    text = text.lower()
    if "database is used by another process" in text:
        return "telegram_session_in_use"
    if any(s in text for s in ("ratelimit", "rate limit", "429", "flood_wait", "floodwait")):
        return "rate_limited"
    if any(s in text for s in ("authrequired", "authorizationerror", "authenticate", "login required", "auth_key", "session_revoked", "not authorized", "401", "403", "temporarily locked")):
        return "auth_required"
    if any(s in text for s in ("notfound", "404", "deleted", "unavailable")):
        return "content_unavailable"
    return "scan_incomplete"


def command(argv, timeout, output=None, *, warnings_are_errors=True):
    # Child output may contain account data, cookies, signed URLs or post text.
    # Never relay it to the caller's logs; only return a bounded error category.
    with tempfile.TemporaryFile() as errors:
        with tempfile.TemporaryFile() as sink:
            try:
                p = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                   stdout=output or sink, stderr=errors,
                                   timeout=timeout, check=False)
            except subprocess.TimeoutExpired:
                raise SyncError("command_timeout") from None
            except OSError:
                raise SyncError("tool_unavailable") from None
            errors.seek(0)
            err = errors.read().decode("utf-8", "replace")
            if p.returncode:
                sink.seek(0)
                raise SyncError(classify(err + sink.read().decode("utf-8", "replace")))
            if "[error]" in err.lower() or (warnings_are_errors and "[warning]" in err.lower()):
                # A partial extraction must never complete a likes baseline.
                raise SyncError(classify(err))


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@contextmanager
def process_lock(state):
    Path(state).mkdir(parents=True, exist_ok=True)
    with open(Path(state) / "worker.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError("worker_already_running") from None
        yield


def safe_extension(value):
    import re
    value = value.lower().lstrip(".")
    return value if re.fullmatch(r"[a-z0-9]{1,12}", value) else "bin"
