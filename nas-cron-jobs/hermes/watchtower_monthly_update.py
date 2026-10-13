#!/usr/bin/env python3
"""Preserve the monthly update operation; notify image changes, not its logs."""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess


LOG_FILE = Path("/home/hermes/.hermes/profiles/lingjun/cron/output/watchtower-monthly-update.log")


def inspect_images(names):
    result = subprocess.run(["docker", "inspect", *names], capture_output=True, text=True, check=True, timeout=30)
    return {row["Name"].lstrip("/"): row["Image"] for row in json.loads(result.stdout)}


def changes(before, after):
    return [f"- {name}：镜像已更新" if name in after else f"- {name}：更新后容器缺失"
            for name, image in before.items() if after.get(name) != image]


def main():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as log:
        try:
            config = json.loads(Path(os.environ.get("CRON_LOCAL_CONFIG", "/home/yuwk/cron/env/hermes.local.json")).read_text())
            result = subprocess.run(["docker", "ps", "--filter", "label=com.centurylinklabs.watchtower.enable=false",
                                     "--format", "{{.Names}}"], capture_output=True, text=True, check=True, timeout=30)
            names = result.stdout.split()
            if not names:
                return 0
            before = inspect_images(names)
            print(datetime.now().isoformat(), "monthly update started", file=log, flush=True)
            result = subprocess.run(["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
                                     "-e", "HTTP_PROXY=" + config["container_proxy_url"],
                                     "-e", "HTTPS_PROXY=" + config["container_proxy_url"],
                                     "containrrr/watchtower:latest", "--run-once", "--cleanup", *names],
                                    stdout=log, stderr=log, timeout=1800)
            remaining = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"],
                                       capture_output=True, text=True, check=True, timeout=30).stdout.split()
            present = [name for name in names if name in remaining]
            after = inspect_images(present) if present else {}
            lines = changes(before, after)
            if result.returncode:
                lines.append(f"- 月度更新：执行失败（退出码 {result.returncode}）")
            if lines:
                print("**容器更新**\n" + "\n".join(lines))
            return result.returncode or int(len(present) != len(names))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(type(exc).__name__, "monthly update failed", file=log)
            print("- 月度更新：执行失败，详细日志已保留")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
