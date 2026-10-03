"""Native one-shot Epic entry; model and browser dependencies load on demand."""

import os
import json
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.model import result, atomic_json


def main():
    context = {
        k: os.environ["BENEFITS_" + k.upper()]
        for k in ("run_id", "platform", "account", "business_date")
    }
    try:
        file = Path(os.environ["EPIC_CONFIG"])
        with file.open("rb") as stream:
            raw = stream.read(32769)
        if len(raw) > 32768: raise ValueError("config_limit")
        from platforms.epic.native import execute
        from platforms.epic.workflow import Paused
        value = asyncio.run(execute(context, json.loads(raw), os.environ["BENEFITS_STATE_DIR"]))
        complete = value.reason in {"complete", "no_current_promotions"} and not value.uncertain
        output = result(context, "ok" if complete else "failed", value.reason,
                        {"claim": "not_applicable" if value.reason == "no_current_promotions"
                         else "complete" if complete else "unknown"})
    except Exception as error:
        from platforms.epic.workflow import Paused
        output = result(context, reason=error.reason if isinstance(error, Paused)
                        else "native_configuration_or_browser_error", business={"claim": "unknown"})
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
