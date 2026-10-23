#!/usr/bin/env python3
"""Scheduled Epic claim for this Mac. Launchd loads the plist in this directory.

Runs the normal one-shot entry with the installed Chrome in the background,
keeps the local runs/results record, and copies the same JSON to the NAS
delivery file. The noon exception report already reads that file and sends
Telegram only when a task is missing, failed, or incomplete.
"""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path.home() / ".config/benefits-automation/runtime"
CONFIG = Path(os.environ.get(
    "EPIC_CONFIG", Path.home() / ".config/benefits-automation/epic.mac.json"))
REMOTE = "yuwk-201"
REMOTE_RUNTIME = "/home/hermes/.hermes/profiles/lingjun/benefits-runtime"
PUBLISH = r"""
import json, os, sys, tempfile
from pathlib import Path
raw = sys.stdin.buffer.read(65537)
if len(raw) > 65536:
    raise SystemExit(2)
value = json.loads(raw)
if (value.get("schema_version") != 1 or value.get("platform") != "epic"
        or value.get("account") != "default"):
    raise SystemExit(2)
root = Path("/home/hermes/.hermes/profiles/lingjun/benefits-runtime")
run_id = value["run_id"]
if not isinstance(run_id, str) or not run_id or "/" in run_id or len(run_id) > 64:
    raise SystemExit(2)
payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()

def write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".result-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o660)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

write(root / "delivery" / "epic.json")
write(root / "runs" / run_id / "result.json")
print(value["execution_status"], value["reason"])
"""


def main():
    if not CONFIG.is_file():
        print("epic_config_missing", file=sys.stderr)
        return 1
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "logs").mkdir(exist_ok=True)
    env = os.environ.copy()
    env["EPIC_CONFIG"] = str(CONFIG)
    env.setdefault("TZ", "Asia/Shanghai")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "platforms/epic/run.py"),
         "--runtime-root", str(RUNTIME), "--account", "default",
         "--timezone", "Asia/Shanghai", "--timeout", "1300", "--execute"],
        cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    log = RUNTIME / "logs/epic-claim.err"
    if completed.stderr:
        log.write_text(completed.stderr[-65536:])
    line = completed.stdout.strip().splitlines()
    if not line:
        print("epic_result_missing", file=sys.stderr)
        return completed.returncode or 1
    try:
        value = json.loads(line[-1])
    except json.JSONDecodeError:
        print("epic_result_invalid", file=sys.stderr)
        return completed.returncode or 1
    encoded = base64.b64encode(PUBLISH.encode()).decode()
    published = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", REMOTE,
         "sudo -n -u hermes python3 -c 'import base64; exec(base64.b64decode(\""
         + encoded + "\"))'"],
        input=json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    status = f'{value.get("run_id")} {value.get("execution_status")} {value.get("reason")}'
    if published.returncode != 0:
        print(status, "publish_failed", file=sys.stderr)
        return 1 if completed.returncode == 0 else completed.returncode
    print(status, "published")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
