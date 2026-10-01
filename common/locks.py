"""Linux advisory leases. Lock files must remain on one local filesystem."""

import fcntl
import os
import time
from pathlib import Path


class Busy(Exception):
    pass


class Lease:
    def __init__(self, path, wait=0):
        self.path = Path(path)
        self.wait = wait
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        end = time.monotonic() + self.wait
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= end:
                    os.close(self.fd)
                    self.fd = None
                    raise Busy("lock_busy")
                time.sleep(min(0.05, max(0, end - time.monotonic())))

    def __exit__(self, *args):
        # Closing (rather than LOCK_UN) preserves the lease in an inherited child.
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
