"""Native GLaDOS workflow: read, submit once, then read-only reconcile."""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.details import metric
from common.model import atomic_json, result
from platforms.glados.provider import (
    Client, Points, ProviderError, accepted, failure, nonnegative, read_points,
)
from platforms.glados.state import Journal


def execute(context, client, state_dir, *, timezone="Asia/Shanghai", status_only=False):
    try:
        journal = Journal(context, state_dir)
    except (ValueError, TypeError, OSError, KeyError, RecursionError):
        return result(context, reason="invalid_action_state")
    before = after = None
    days_before = days_after = None
    snapshot = Points(None, None, None, None)
    checkin = "complete" if journal.status == "complete" else "unknown"
    reward = journal.reward

    def finish(reason, execution="ok"):
        current = after if after is not None else before
        return result(context, execution, reason, {
            "checkin": checkin,
            "reward": "complete" if checkin == "complete" and reward is not None else "unknown",
            "balance": "complete" if after is not None else "unknown",
        }, {"metrics": {
            "balance": metric("points", current, before=before, after=after,
                              delta=after - before if before is not None and after is not None else None),
            "reward": metric("points", reward),
            "streak": metric("days", snapshot.streak),
            "remaining_days": metric("days", days_after if days_after is not None else days_before,
                                     before=days_before, after=days_after),
        }, "items": [{"id": "checkin", "name": "GLaDOS 签到", "status": checkin, "reason": reason}]})

    def observe():
        nonlocal snapshot, after, checkin, reward
        snapshot = read_points(client.points(), context["business_date"], timezone)
        after = snapshot.balance
        if snapshot.signed is True:
            checkin = "complete"
            if snapshot.reward is not None:
                reward = snapshot.reward
            journal.set("complete", reward)

    try:
        try:
            days_before = client.status()
        except ProviderError as error:
            if str(error) == "authentication_invalid":
                return finish("authentication_invalid", "failed")
        observe()
        before = after
        if checkin == "complete":
            days_after = days_before
            return finish("checkin_confirmed" if reward is not None and after is not None
                          else "checkin_confirmed_details_unavailable")
        if status_only:
            checkin = "incomplete" if snapshot.signed is False else "unknown"
            days_after = days_before
            return finish("checkin_not_completed" if snapshot.signed is False else "checkin_status_unconfirmed")
        if journal.status == "pending":
            return finish("checkin_pending_confirmation")
        if snapshot.signed is None:
            return finish("checkin_status_unconfirmed")

        # Sync the intent before the request may leave this process.
        journal.set("pending")
        write_error = None
        try:
            reply = client.checkin()
            if accepted(reply):
                checkin = "complete"
                reward = nonnegative(reply.get("points")) if reply["code"] == 0 else None
                journal.set("complete", reward)
            else:
                write_error = failure(reply)
                if write_error in {"authentication_invalid", "device_mismatch", "automated_checkin_rejected"}:
                    journal.set("unknown")  # Explicit rejection confirms this request did not check in.
                    checkin = "blocked"
        except ProviderError as error:
            write_error = str(error)
            if write_error in {"authentication_invalid", "device_mismatch", "automated_checkin_rejected"}:
                journal.set("unknown")
                checkin = "blocked"

        # Fresh reads are the only recovery after an ambiguous POST, now and in later runs.
        after = None
        try:
            observe()
        except ProviderError as error:
            return finish(str(error), "ok" if checkin == "complete" else "failed")
        try:
            days_after = client.status()
        except ProviderError:
            pass
        if checkin == "complete":
            return finish("checkin_confirmed" if reward is not None and after is not None
                          else "checkin_confirmed_details_unavailable")
        return finish(write_error or "checkin_pending_confirmation",
                      "failed" if write_error == "authentication_invalid" else "ok")
    except ProviderError as error:
        return finish(str(error), "failed")
    except (ValueError, OSError):
        return finish("configuration_or_io_error", "failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    args = parser.parse_args()
    context = {key: os.environ["BENEFITS_" + key.upper()]
               for key in ("run_id", "platform", "account", "business_date")}
    try:
        cookie = os.environ.get("GLADOS_COOKIE", "")
        origin = os.environ.get("GLADOS_ORIGIN", "")
        user_agent = os.environ.get("GLADOS_USER_AGENT", "")
        config = os.environ.get("COOKIECLOUD_CONFIG")
        if config:
            # Validate the non-secret settings before contacting the credential source.
            from platforms.glados.provider import validate_settings
            validate_settings(origin, "gld:sess=validate; gld:sess.sig=validate", user_agent)
            from common.cookiecloud import cookie_header
            from urllib.parse import urlsplit
            try:
                cookie = cookie_header(config, urlsplit(origin).hostname)
            except (ValueError, OSError, ImportError, TypeError, KeyError):
                raise ProviderError("cookiecloud_unavailable") from None
        client = Client(origin, cookie, user_agent, os.environ.get("GLADOS_TOKEN", ""),
                        os.environ.get("GLADOS_PROXY"))
        output = execute(context, client, os.environ["BENEFITS_STATE_DIR"],
                         timezone=args.timezone, status_only=args.status)
    except ProviderError as error:
        output = result(context, reason=str(error))
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0 if output["execution_status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
