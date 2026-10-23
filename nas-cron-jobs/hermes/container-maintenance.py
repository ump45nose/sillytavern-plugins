#!/usr/bin/env python3
"""Audit or start existing persistent containers using the canonical boot plan."""

import argparse
import fcntl
from pathlib import Path
import runpy
import time


def confirmed_ready(boot, name):
    # Confirm a failed observation before reporting it during Docker changes.
    for attempt in range(3):
        if boot["ready"](name):
            return True
        if attempt < 2:
            time.sleep(1)
    return False


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
                errors.append(f"- {name}：容器缺失")
                continue
            if data["State"]["Status"] != "running" and args.mode == "repair":
                _, error = boot["ensure_started"](name, dependencies, start_timeout=30, dependency_timeout=0)
                if error:
                    errors.append(f"- {name}：{error}")
                    continue
                deadline = time.monotonic() + 30
                while not boot["ready"](name) and time.monotonic() < deadline:
                    time.sleep(1)
                print(f"- {name}：已启动")
            if not confirmed_ready(boot, name):
                errors.append(f"- {name}：运行或健康检查异常")
        for message in errors:
            print(message)
        return int(bool(errors))
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
