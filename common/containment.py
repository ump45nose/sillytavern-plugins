"""Process-local Linux browser containment; no service or machine settings.

The one-shot launcher must have no other children when entering this scope.
A pending marker survives launcher SIGKILL. Same-boot markers are not guessed
away: detached descendants can no longer be attributed after their owner dies.
"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import signal
import sys
import time
import threading
import uuid

from .model import atomic_json


class ContainmentError(OSError):
    pass


def boot_id():
    value = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError("invalid_boot_id")
    except ValueError:
        raise ContainmentError("browser_containment_unavailable") from None
    return value


def children():
    try:
        value = Path(f"/proc/self/task/{os.getpid()}/children").read_text()
        pids = [int(value) for value in value.split()]
    except FileNotFoundError:
        # Some Linux runtimes omit the children file. Inspect parent IDs, never
        # process names. Pidfds plus waitpid still establish ownership before kill.
        pids = []
        with os.scandir("/proc") as entries:
            for count, entry in enumerate(entries):
                if count > 16384:
                    raise ContainmentError("browser_cleanup_unverified")
                if not entry.name.isdecimal():
                    continue
                try:
                    stat = Path(entry.path, "stat").read_text()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                fields = stat[stat.rfind(")") + 2 :].split()
                if int(fields[1]) == os.getpid():
                    pids.append(int(entry.name))
    if len(pids) > 1024:
        raise ContainmentError("browser_cleanup_unverified")
    return pids


def inspect_marker(path):
    """Read at most 4 KiB; an invalid marker also blocks browser execution."""
    try:
        with Path(path).open("rb") as stream:
            raw = stream.read(4097)
    except FileNotFoundError:
        return None
    if len(raw) > 4096:
        raise ContainmentError("browser_cleanup_unverified")
    try:
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "run_id", "boot_id", "launcher_pid"}
            or value["schema_version"] != 1
            or not isinstance(value["run_id"], str)
            or not isinstance(value["boot_id"], str)
            or len(value["boot_id"]) != 36
            or type(value["launcher_pid"]) is not int
            or value["launcher_pid"] <= 0
        ):
            raise ValueError("invalid_marker")
        if str(uuid.UUID(value["boot_id"])) != value["boot_id"]:
            raise ValueError("invalid_boot_id")
    except (ValueError, TypeError):
        raise ContainmentError("browser_cleanup_unverified") from None
    return value


class BrowserScope:
    """Held inside the global browser lease; owns only this launcher's children."""

    def __init__(self, marker, run_id, *, report=None):
        self.marker = Path(marker)
        self.run_id = run_id
        self.libc = None
        self.previous = ctypes.c_int()
        self.cleanup_verified = False
        self.report = report or (lambda record: print(json.dumps(record), file=sys.stderr, flush=True))

    def __enter__(self):
        current_boot = boot_id()
        pending = inspect_marker(self.marker)
        if pending and pending["boot_id"] == current_boot:
            raise ContainmentError("browser_cleanup_unverified")
        # Another boot proves all previous processes are gone. No same-boot PID
        # guessing, process-name matching, or stale-age based marker deletion.
        if (
            threading.active_count() != 1
            or threading.current_thread() is not threading.main_thread()
            or children()
        ):
            raise ContainmentError("browser_containment_in_use")
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise ContainmentError("browser_containment_unavailable")
        try:
            fd = os.pidfd_open(os.getpid())
            try:
                signal.pidfd_send_signal(fd, 0)
            finally:
                os.close(fd)
        except OSError:
            raise ContainmentError("browser_containment_unavailable") from None
        self.libc = ctypes.CDLL(None, use_errno=True)
        if self.libc.prctl(37, ctypes.byref(self.previous), 0, 0, 0) != 0:
            raise ContainmentError("browser_containment_unavailable")
        if self.libc.prctl(36, 1, 0, 0, 0) != 0:
            raise ContainmentError("browser_containment_unavailable")
        try:
            atomic_json(
                self.marker,
                {
                    "schema_version": 1,
                    "run_id": self.run_id,
                    "boot_id": current_boot,
                    "launcher_pid": os.getpid(),
                },
            )
        except BaseException:
            self.libc.prctl(36, self.previous.value, 0, 0, 0)
            raise
        return self

    def cleanup(self, timeout=2.0):
        """Kill adopted children by pidfd; reap them, then their adopted children.

        Caller first terminates/waits for its direct adapter. waitpid confirms
        parentage before sending any signal; pidfds prevent PID reuse mistakes.
        This scope is only for the standalone single-threaded launcher.
        """
        end = time.monotonic() + timeout
        def failed(reason, **details):
            self.report({"event": "browser_cleanup_failed", "reason": reason, **details})
            return False

        while True:
            try:
                remaining = children()
                if not remaining:
                    self.cleanup_verified = True
                    return True
                for pid in remaining:
                    try:
                        reaped, _ = os.waitpid(pid, os.WNOHANG)
                    except ChildProcessError:
                        return failed("ownership_unconfirmed", pid=pid)
                    if reaped:
                        continue
                    try:
                        fd = os.pidfd_open(pid)
                    except ProcessLookupError:
                        continue
                    try:
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    finally:
                        os.close(fd)
            except (OSError, ValueError) as error:
                return failed("cleanup_error", type=type(error).__name__, errno=getattr(error, "errno", None))
            if time.monotonic() >= end:
                return failed("cleanup_deadline", pids=remaining)
            time.sleep(0.02)

    def __exit__(self, *args):
        try:
            self.cleanup()
        finally:
            if self.libc.prctl(36, self.previous.value, 0, 0, 0) != 0:
                self.cleanup_verified = False
                raise ContainmentError("browser_cleanup_unverified")
        if self.cleanup_verified:
            try:
                self.marker.unlink()
            except OSError:
                self.cleanup_verified = False
                raise ContainmentError("browser_cleanup_unverified") from None


def main():
    parser = argparse.ArgumentParser(description="Read-only browser cleanup inspection")
    parser.add_argument("--runtime-root", required=True, type=Path)
    args = parser.parse_args()
    marker = args.runtime_root.expanduser().resolve() / "locks/browser-cleanup.json"
    try:
        pending = inspect_marker(marker)
        if pending is None:
            status = "no_pending_cleanup"
        elif pending["boot_id"] != boot_id():
            status = "previous_boot_next_run_can_recover"
        else:
            status = "same_boot_cleanup_requires_operator_verification_or_host_restart"
        print(json.dumps({"status": status, "pending": pending}))
    except (OSError, ValueError):
        print(json.dumps({"status": "browser_cleanup_unverified"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
