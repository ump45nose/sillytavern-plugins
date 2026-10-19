"""Points snapshot only; intentionally does not expose a sign-in action."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.details import metric
from common.model import atomic_json, result
from platforms.yanxuan.client import Client, QueryError


def execute(context, cookie, *, user_agent="Mozilla/5.0", proxy=None, opener=None):
    try:
        observed = Client(
            cookie, user_agent=user_agent, proxy=proxy, opener=opener
        ).snapshot()
    except QueryError as error:
        return result(context, reason=str(error), business={"points_query": "unknown"})
    return result(
        context, "ok", "points_snapshot_observed", {"points_query": "complete"},
        {
            "metrics": {key: metric("points", value) for key, value in observed.items()},
            "items": [],
        },
    )


def main():
    context = {
        key: os.environ["BENEFITS_" + key.upper()]
        for key in ("run_id", "platform", "account", "business_date")
    }
    output = execute(
        context,
        os.environ.get("YANXUAN_COOKIE", ""),
        user_agent=os.environ.get("YANXUAN_USER_AGENT", "Mozilla/5.0"),
        proxy=os.environ.get("YANXUAN_PROXY"),
    )
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
