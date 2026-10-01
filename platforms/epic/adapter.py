"""Report the native integration gap without requiring the retired application.

compat.py remains an offline source-audit tool. The new execution path must not
import or require the entire old runtime just to report its current readiness.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.model import result, atomic_json


def main():
    context = {
        k: os.environ["BENEFITS_" + k.upper()]
        for k in ("run_id", "platform", "account", "business_date")
    }
    output = result(context, reason="native_browser_and_approval_bindings_pending")
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
