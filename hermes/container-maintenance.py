#!/usr/bin/env python3
"""Audit or start existing persistent containers using the canonical boot plan."""

import argparse
import fcntl
from pathlib import Path
import runpy
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("audit", "repair"))
    args = parser.parse_args()
    boot = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/container-boot.py"))
    lock = None
    if args.mode == "repair":
        lock = boot["open_lock"]()
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            return 0  # The boot service is already reconciling the same plan.
    errors = []
    try:
        for _, name, dependencies in boot["load_order"]():
            data = boot["inspect"](name)
            if not data:
                errors.append(f"missing container: {name}")
                continue
            if data["State"]["Status"] != "running" and args.mode == "repair":
                if any(not boot["ready"](dependency) for dependency in dependencies):
                    errors.append(f"prerequisite unavailable: {name}")
                    continue
                result = boot["run"]("docker", "start", name, timeout=30)
                if not result or result.returncode:
                    errors.append(f"start failed: {name}")
                    continue
                deadline = time.monotonic() + 30
                while not boot["ready"](name) and time.monotonic() < deadline:
                    time.sleep(1)
                print(f"container started: {name}")
            if not boot["ready"](name):
                errors.append(f"container unavailable: {name}")
        for message in errors:
            print(message)
        return int(bool(errors))
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
