"""Finite process-group supervisor; no claim to contain a child that calls setsid()."""

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass


@dataclass
class Outcome:
    returncode: int | None
    timed_out: bool = False
    interrupted: bool = False
    spawn_error: bool = False


class LogSink:
    """Bound disk and memory; redact exact credentials even across read chunks."""

    def __init__(self, path, secrets=(), limit=1048576):
        self.f = open(path, "xb")
        os.chmod(path, 0o600)
        self.limit = limit
        self.written = 0
        self.secrets = sorted({s.encode() for s in secrets if s}, key=len, reverse=True)
        self.keep = max([len(x) for x in self.secrets] + [1]) - 1
        self.pending = b""

    def feed(self, data, final=False):
        if self.written >= self.limit:
            self.pending = b""
            return
        self.pending += data
        stop = len(self.pending) if final else max(0, len(self.pending) - self.keep)
        # Scan original bytes, holding enough lookahead for cross-chunk secrets.
        out = bytearray()
        i = 0
        while i < stop:
            secret = next(
                (s for s in self.secrets if self.pending.startswith(s, i)), None
            )
            if secret:
                out.extend(b"[REDACTED]")
                i += len(secret)
            else:
                out.append(self.pending[i])
                i += 1
        self.pending = self.pending[i:]
        remaining = max(0, self.limit - self.written)
        self.f.write(out[:remaining])
        self.written += min(len(out), remaining)

    def close(self):
        self.feed(b"", True)
        self.f.close()


def group_alive(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def supervise(
    argv, cwd, env, timeout, sink, lease_fds=(), grace=1.0, interactive=False
):
    """Timeout includes TERM grace. Always clean group, including exited leader's children.

    Child inherits leases so an abruptly killed launcher doesn't immediately unlock
    a still-running direct adapter. This is not a cgroup/daemon containment boundary.
    """
    start = time.monotonic()
    end = start + timeout
    cancel = [False]
    previous = {}

    def interrupt(sig, frame):
        cancel[0] = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, interrupt)
    proc = None
    sel = selectors.DefaultSelector()
    outcome = Outcome(None)
    try:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                env=env,
                start_new_session=True,
                stdin=None if interactive else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                pass_fds=tuple(lease_fds),
            )
        except OSError:
            outcome.spawn_error = True
            return outcome
        os.set_blocking(proc.stdout.fileno(), False)
        sel.register(proc.stdout, selectors.EVENT_READ)
        terminating = None
        kill_at = None
        while True:
            now = time.monotonic()
            rc = proc.poll()
            if terminating is None and (
                cancel[0] or now >= end - grace or rc is not None
            ):
                outcome.interrupted = cancel[0]
                outcome.timed_out = rc is None and not cancel[0]
                terminating = now
                kill_at = min(now + grace, end)
                signal_group(proc.pid, signal.SIGTERM)
            if terminating is not None and now >= kill_at:
                signal_group(proc.pid, signal.SIGKILL)
                break
            if terminating is not None and rc is not None and not group_alive(proc.pid):
                break
            for key, _ in sel.select(0.05):
                chunk = os.read(key.fd, 16384)
                if chunk:
                    sink.feed(chunk)
                else:
                    sel.unregister(key.fileobj)
        # Bound draining after kill too (a detached child may keep a pipe open).
        signal_group(proc.pid, signal.SIGKILL)
        proc.wait(timeout=2)
        drain_end = time.monotonic() + 0.2
        while sel.get_map() and time.monotonic() < drain_end:
            try:
                chunk = os.read(proc.stdout.fileno(), 16384)
            except BlockingIOError:
                break
            if not chunk:
                break
            sink.feed(chunk)
        outcome.returncode = proc.returncode
        return outcome
    finally:
        if proc is not None:
            signal_group(proc.pid, signal.SIGKILL)
            if proc.poll() is None:
                proc.wait(timeout=2)
            proc.stdout.close()
        sel.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
