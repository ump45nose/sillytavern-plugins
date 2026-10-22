"""One-shot Linux task launcher, using only the Python standard library."""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from zoneinfo import ZoneInfo
from .locks import Lease, Busy
from .model import result, read_result, atomic_json
from .lifecycle import LogSink, supervise
from .containment import BrowserScope, ContainmentError
from .task import Task

ROOT = Path(__file__).resolve().parents[1]
EXIT = {"ok": 0, "failed": 1, "timeout": 124, "busy": 75}


def run(task: Task):
    started_at, started = datetime.now(timezone.utc).isoformat(), time.monotonic()
    def stamp(value):
        value.setdefault("started_at", started_at)
        value.setdefault("finished_at", datetime.now(timezone.utc).isoformat())
        value.setdefault("duration_ms", round((time.monotonic() - started) * 1000))
        return value
    platform = task.platform
    os.umask(0o077)
    p = argparse.ArgumentParser(
        description=f"Native one-shot {platform} task; no network without --execute"
    )
    p.add_argument("--account", default="default")
    p.add_argument("--runtime-root", required=True, type=Path)
    p.add_argument("--timeout", type=float, default=task.timeout)
    p.add_argument("--lock-wait", type=float, default=0)
    p.add_argument("--timezone", default="Asia/Shanghai")
    p.add_argument("--execute", action="store_true")
    p.add_argument("--node", default="node")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--browser-cache", type=Path,
                   help="Absolute installed Playwright browser cache")
    if task.configure:
        task.configure(p)
    a = p.parse_args()
    if task.validate:
        task.validate(p, a)
    interactive = getattr(a, "login", False)
    if a.browser_cache and not a.browser_cache.is_absolute():
        p.error("browser-cache must be absolute")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,48}", a.account):
        p.error("account must be an opaque identifier (not an email)")
    if not 2 <= a.timeout <= 86400 or not 0 <= a.lock_wait <= 300:
        p.error("timeout must be 2..86400; lock-wait 0..300")
    try:
        today = datetime.now(ZoneInfo(a.timezone)).date().isoformat()
    except Exception:
        p.error("unknown timezone")
    context = {
        "run_id": str(uuid.uuid4()),
        "platform": platform,
        "account": a.account,
        "business_date": today,
    }
    run_dir = None
    output = result(context, reason="execution_not_requested")
    try:
        runtime = a.runtime_root.expanduser().resolve()
        if runtime == ROOT or ROOT in runtime.parents:
            p.error("runtime-root must be outside the source repository")
        run_dir = runtime / "runs" / context["run_id"]
        state = runtime / "state" / platform / a.account
        run_dir.mkdir(parents=True, mode=0o700)
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        with ExitStack() as stack:
            task_lease = stack.enter_context(
                Lease(runtime / "locks" / f"{platform}.{a.account}.lock", a.lock_wait)
            )
            leases = [task_lease.fd]
            if task.browser:
                leases.append(
                    stack.enter_context(
                        Lease(runtime / "locks" / "browser.lock", a.lock_wait)
                    ).fd
                )
            latest_dir = runtime / "results" / platform / a.account
            if task.result_partition:
                latest_dir = latest_dir / task.result_partition(a)
            # A confirmed action does not complete the whole platform. Adapters
            # reconcile their own action journals and current site state.
            if a.execute:
                adapter = task.directory / task.adapter
                argv = (task.command(a) if task.command else
                        [a.node if adapter.suffix == ".cjs" else a.python, str(adapter)])
                env = {
                    k: os.environ[k]
                    for k in ("PATH", "LANG", "LC_ALL", "TZ")
                    if k in os.environ
                }
                env.update({k: os.environ[k] for k in task.environment if k in os.environ})
                if any(len(v) > 65536 for v in env.values()):
                    raise ValueError("environment_value_too_large")
                env.update(
                    {f"BENEFITS_{k.upper()}": str(v) for k, v in context.items()}
                )
                if interactive and "DISPLAY" in os.environ:
                    env["DISPLAY"] = os.environ["DISPLAY"]
                if a.browser_cache:
                    env["PLAYWRIGHT_BROWSERS_PATH"] = str(a.browser_cache)
                env.update(
                    BENEFITS_RESULT_PATH=str(run_dir / "adapter-result.json"),
                    BENEFITS_STATE_DIR=str(state),
                    BENEFITS_LAST_CONFIRMED_PATH=str(
                        latest_dir / "last-confirmed.json"
                    ),
                    HOME=str(state),
                    TMPDIR=str(run_dir),
                    BENEFITS_PYTHON=a.python,
                )
                sink = LogSink(
                    run_dir / "output.log",
                    [os.environ[k] for k in task.environment if k in os.environ],
                )
                scope = None
                try:
                    with ExitStack() as process_stack:
                        if task.browser:
                            scope = process_stack.enter_context(
                                BrowserScope(
                                    runtime / "locks/browser-cleanup.json",
                                    context["run_id"],
                                    report=lambda record: sink.feed((json.dumps(record) + "\n").encode()),
                                )
                            )
                        outcome = supervise(
                            argv,
                            ROOT,
                            env,
                            a.timeout,
                            sink,
                            leases,
                            interactive=interactive,
                        )
                finally:
                    # Even cleanup/reporting exceptions must not erase a valid
                    # partial result that the adapter already published.
                    try:
                        output = read_result(run_dir / "adapter-result.json", context)
                    except (OSError, ValueError, TypeError):
                        output = result(context, reason="invalid_or_missing_result")
                    sink.close()
                # Execution failure does not revoke independently confirmed
                # business evidence, including partial progress before a deadline.
                if scope is not None and not scope.cleanup_verified:
                    output.update(
                        execution_status="failed", reason="browser_cleanup_unverified"
                    )
                elif outcome.spawn_error:
                    output.update(
                        execution_status="failed", reason="runtime_unavailable"
                    )
                elif outcome.timed_out:
                    output.update(
                        execution_status="timeout", reason="deadline_exceeded"
                    )
                elif outcome.interrupted:
                    output.update(execution_status="failed", reason="interrupted")
                elif outcome.returncode and output["execution_status"] == "ok":
                    output.update(
                        execution_status="failed", reason="process_failed_after_result"
                    )
            # Latest is serialized by the same account lock; no append-only unbounded ledger.
            if a.execute:
                atomic_json(latest_dir / "latest.json", stamp(output))
                if output["business"].get("checkin") == "complete":
                    atomic_json(latest_dir / "last-confirmed.json", output)
    except Busy:
        output = result(context, "busy", "lock_busy")
    except ContainmentError as error:
        output.update(execution_status="failed", reason=str(error))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
        output.update(execution_status="failed", reason="configuration_or_io_error")
    # Storage failure must not suppress the scheduler's stdout result. Preserve
    # business evidence even if an artifact could not be persisted.
    try:
        stamp(output)
        if run_dir is not None:
            atomic_json(run_dir / "result.json", output)
    except (ValueError, OSError):
        output.update(execution_status="failed", reason="configuration_or_io_error")
    print(json.dumps(output, ensure_ascii=False))
    if output["execution_status"] == "ok" and any(
        v not in {"complete", "not_applicable"} for v in output["business"].values()
    ):
        return 3
    return EXIT[output["execution_status"]]
