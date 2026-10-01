"""Pinned dailycheckin provider; one account per invocation, no write retry."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.model import result, atomic_json


def classify(rows, today):
    if not isinstance(rows, list):
        return False
    fields = {
        row.get("name"): str(row.get("value", ""))
        for row in rows
        if isinstance(row, dict)
    }
    reward = fields.get("今日签到", "")
    return (
        today.replace("-", "") in reward
        and "每日登录奖励" in reward
        and "签到失败" not in fields
    )


def execute(context, provider, session_factory, cookie, proxy=None):
    if not cookie or "\n" in cookie or "\r" in cookie:
        return result(context, reason="missing_or_invalid_cookie")
    try:
        with session_factory() as session:
            session.headers.update(
                {
                    "Cookie": cookie,
                    "User-Agent": os.getenv("V2EX_USER_AGENT", "Mozilla/5.0"),
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
            )
            if proxy:
                session.proxies.update({"http": proxy, "https": proxy})
            success = classify(provider.sign(session), context["business_date"])
        return result(
            context,
            "ok" if success else "failed",
            "reward_confirmed" if success else "reward_not_confirmed",
            {
                "checkin": "complete" if success else "unknown",
                "reward": "complete" if success else "unknown",
            },
        )
    except Exception:
        return result(context, reason="provider_error")


def main():
    context = {
        k: os.environ["BENEFITS_" + k.upper()]
        for k in ("run_id", "platform", "account", "business_date")
    }
    try:
        import requests
        from platforms.v2ex.provider import V2ex
    except Exception:
        output = result(context, reason="dependency_unavailable_or_incompatible")
    else:

        class BoundedSession(requests.Session):
            def request(self, method, url, **kwargs):
                kwargs["timeout"] = 30
                # The legacy provider passes verify=False; do not inherit that unsafe behavior.
                kwargs["verify"] = True
                return super().request(method, url, **kwargs)

        output = execute(
            context,
            V2ex,
            BoundedSession,
            os.getenv("V2EX_COOKIE", ""),
            os.getenv("V2EX_PROXY"),
        )
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
