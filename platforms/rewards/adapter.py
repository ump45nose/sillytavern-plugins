"""Native preflight gate; no upstream import until integration checks are closed."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.model import result, atomic_json
from platforms.rewards.compat import preflight


def main():
    context = {
        k: os.environ["BENEFITS_" + k.upper()]
        for k in ("run_id", "platform", "account", "business_date")
    }
    root = os.getenv("REWARDS_UPSTREAM_DIR")
    try:
        reason = preflight(root) if root else "upstream_not_configured"
    except (OSError, ValueError, SyntaxError):
        reason = "dependency_incompatible"
    output = result(context, reason=reason or "integration_not_ready")
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
