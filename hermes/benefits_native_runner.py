#!/usr/bin/env python3
"""Hermes deployment glue; business stays in benefits-automation."""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CONFIG = Path(os.environ.get("HERMES_HOME", "/home/hermes/.hermes/profiles/lingjun")) / "benefits-deployment.json"


def bounded(path, limit=65536):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("deployment_input_limit")
    return json.loads(raw)


def main(task_id):
    started_at, started = datetime.now(timezone.utc).isoformat(), time.monotonic()
    cfg = bounded(CONFIG)
    task = cfg["tasks"][task_id]
    platform = task.get("platform", task_id)
    if task.get("enabled", True) is False:
        print(task["label"] + "：已停用")
        return 0
    repo, runtime = Path(cfg["repository"]), Path(cfg["runtime_root"])
    sys.path.insert(0, str(repo))
    from common.model import result, validate, atomic_json
    day = datetime.now(ZoneInfo(cfg["timezone"])).date().isoformat()
    context = {"run_id": str(uuid.uuid4()), "platform": platform,
               "account": task["account"], "business_date": day}
    output = result(context, reason="launcher_failed", business={"task": "unknown"})
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TZ") if k in os.environ}
    env.update(task.get("environment", {}))
    python = task["python"]
    argv = [python, str(repo / "platforms" / platform / "run.py"),
            "--runtime-root", str(runtime), "--account", task["account"],
            "--timezone", cfg["timezone"], "--python", python,
            "--node", cfg["node"], "--browser-cache", cfg["browser_cache"],
            "--timeout", str(task["timeout"]), "--lock-wait", "300", "--execute",
            *task.get("arguments", [])]
    try:
        if task.get("credentials"):
            secret = bounded(task["credentials"])
            if (not isinstance(secret, dict) or
                    any(k not in task["credential_names"] or not isinstance(v, str) or len(v) > 65536
                        for k, v in secret.items())):
                raise ValueError("invalid_task_credentials")
            env.update(secret)
        child = subprocess.run(argv, env=env, cwd=repo, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True,
                               timeout=task["timeout"] + 340)
        if len(child.stdout.encode()) > 65536:
            raise ValueError("launcher_result_limit")
        candidate = json.loads(child.stdout)
        if not isinstance(candidate, dict):
            raise ValueError("invalid_result")
        run_id = candidate.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", run_id):
            raise ValueError("invalid_run_id")
        output = validate(candidate, {**context, "run_id": run_id})
        if child.returncode not in {0, 1, 3, 75, 124}:
            output.update(execution_status="failed", reason="launcher_exit_unexpected")
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        pass
    # Reuse the platform's per-run record, including attempts that never reached it.
    output.setdefault("started_at", started_at)
    output.setdefault("finished_at", datetime.now(timezone.utc).isoformat())
    output.setdefault("duration_ms", round((time.monotonic() - started) * 1000))
    atomic_json(runtime / "runs" / output["run_id"] / "result.json", output)
    # A prior successful latest must not conceal busy/failure.
    atomic_json(runtime / "delivery" / (task_id + ".json"), output)
    print(task["label"] + "：结果已保存（" + output["execution_status"] + "）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
