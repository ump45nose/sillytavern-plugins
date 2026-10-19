#!/usr/bin/env python3
"""Actual Selenium/sandbox smoke, under the normal shared browser lease.

Use the existing common runtime-root. This opens chrome://sandbox only, never
Rainyun, and uses the configured binary/driver/provider paths without signing in.
"""

import os
from pathlib import Path
import re
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.model import atomic_json, result
from common.runner import run
from common.task import Task
from platforms.rainyun.adapter import load_config
from platforms.rainyun.browser import Browser, RainyunError


def worker():
    context = {k: os.environ["BENEFITS_" + k.upper()]
               for k in ("run_id", "platform", "account", "business_date")}
    browser = None
    try:
        config = load_config(os.environ.get("RAINYUN_CONFIG"))
        browser = Browser(config, Path(os.environ["BENEFITS_STATE_DIR"]))
        browser.open()
        browser.driver.get("chrome://sandbox/")
        text = browser.driver.find_element("tag name", "body").text
        namespace = re.search(r"Namespace sandbox\s+Yes", text)
        seccomp = re.search(r"Seccomp-BPF sandbox\s+Yes", text, re.I)
        args = browser.driver.execute_cdp_cmd("Browser.getBrowserCommandLine", {})["arguments"]
        if not namespace or not seccomp or "--no-sandbox" in args:
            raise RainyunError("sandbox_not_confirmed")
        output = result(context, "ok", "browser_sandbox_confirmed",
                        {"browser": "complete", "sandbox": "complete"})
    except RainyunError as error:
        output = result(context, reason=str(error))
    except Exception:
        # This smoke never reads credentials into a page or accesses Rainyun.
        # Keep runtime failures in the normal private, bounded run log.
        traceback.print_exc()
        output = result(context, reason="browser_smoke_failed")
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                if "output" in locals():
                    output.update(execution_status="failed", reason="browser_cleanup_unverified")
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


TASK = Task("rainyun-smoke", Path(__file__).resolve().parent, Path(__file__).name, 90,
            frozenset(["RAINYUN_CONFIG"]), browser=True,
            command=lambda args: [args.python, str(Path(__file__).resolve()), "--worker"])

if __name__ == "__main__":
    raise SystemExit(worker() if sys.argv[1:] == ["--worker"] else run(TASK))
