"""Pinned dailycheckin provider; one account per invocation, no write retry."""

import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.model import result, atomic_json
from common.details import metric
import re


def delivery_details(rows):
    fields = {r.get("name"): str(r.get("value", "")) for r in rows if isinstance(r, dict)}
    streak = re.fullmatch(r"(?:已连续签到\s*)?(\d{1,6})天", fields.get("签到天数", "").strip())
    # The provider's legacy balance column is not a verified unit/value contract.
    # Do not reinterpret that column as the reward or invent an earned amount.
    return {"metrics": {"streak": metric("days", int(streak[1]) if streak else None),
                        "reward": metric("coins")}, "items": []}
from platforms.v2ex.state import Journal


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


def execute(
    context,
    provider,
    session_factory,
    cookie,
    proxy=None,
    state_dir=None,
    confirmed_path=None,
):
    if not cookie or "\n" in cookie or "\r" in cookie:
        return result(context, reason="missing_or_invalid_cookie")
    try:
        journal = Journal(context, state_dir, confirmed_path)
    except Exception:
        return result(context, reason="invalid_action_state")

    def confirmed():
        complete = journal.status == "complete"
        return {
            "checkin": "complete" if complete else "unknown",
            "reward": "complete" if complete else "unknown",
        }

    already_complete = journal.status == "complete"
    try:
        with session_factory() as session:
            session.trust_env = False
            session.headers.update(
                {
                    "Cookie": cookie,
                    "User-Agent": os.getenv("V2EX_USER_AGENT", "Mozilla/5.0"),
                    "Accept-Language": "zh-CN,zh;q=0.9",
                }
            )
            if proxy:
                session.proxies.update({"http": proxy, "https": proxy})

            def on_balance(rows):
                if classify(rows, context["business_date"]):
                    journal.set("complete")

            write_started = False

            def before_write():
                nonlocal write_started
                journal.set("pending")
                write_started = True

            try:
                rows = provider.sign(
                    session,
                    read_only=already_complete or journal.status == "pending",
                    before_write=before_write,
                    on_balance=on_balance,
                )
            except Exception:
                if not write_started:
                    raise
                # Redemption may have succeeded before a redirect/transport
                # error. Reconcile once in the same run, never redeem again.
                rows = provider.sign(
                    session, read_only=True, on_balance=on_balance
                )
            on_balance(rows)
        success = journal.status == "complete"
        return result(
            context,
            "ok" if success else "failed",
            "reward_confirmed" if success else "reward_not_confirmed",
            confirmed(),
            delivery_details(rows),
        )
    except Exception:
        return result(context, "ok" if already_complete else "failed",
                      "reward_confirmed_details_unavailable" if already_complete else "provider_error",
                      confirmed(), {"metrics": {"streak": metric("days"), "reward": metric("coins")}, "items": []})


def bounded_session(base):
    """Enforce the cap while decoding the body, before requests buffers .text."""

    class BoundedSession(base):
        def resolve_redirects(self, *args, **kwargs):
            # requests also builds Response.next when allow_redirects=False;
            # that path eagerly consumes redirect bodies unless disabled here.
            return iter(())

        def request(self, method, url, **kwargs):
            kwargs.update(timeout=30, verify=True, stream=True, allow_redirects=False)
            response = super().request(method, url, **kwargs)
            try:
                # Redirect bodies are otherwise consumed without bounds by requests.
                if 300 <= response.status_code < 400:
                    raise ValueError("unexpected_redirect")
                size = response.headers.get("Content-Length")
                if size is not None and int(size) > 1048576:
                    raise ValueError("response_limit")
                chunks, total = [], 0
                for chunk in response.iter_content(chunk_size=65536):
                    total += len(chunk)
                    if total > 1048576:
                        raise ValueError("response_limit")
                    chunks.append(chunk)
                response._content = b"".join(chunks)
                response._content_consumed = True
                return response
            finally:
                response.close()

    return BoundedSession


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
        output = execute(
            context,
            V2ex,
            bounded_session(requests.Session),
            os.getenv("V2EX_COOKIE", ""),
            os.getenv("V2EX_PROXY"),
            os.environ.get("BENEFITS_STATE_DIR"),
            os.environ.get("BENEFITS_LAST_CONFIRMED_PATH"),
        )
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
