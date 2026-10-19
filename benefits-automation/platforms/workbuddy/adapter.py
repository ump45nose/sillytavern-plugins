"""Daily WorkBuddy operations with readback and durable single-send intent."""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.details import metric
from common.locks import Busy, Lease
from common.model import atomic_json, result
from platforms.workbuddy.client import Client, HTTP, amount, boolean, field
from platforms.workbuddy.state import Credentials, Journal, WorkBuddyError, credential_path


def details(before, after, reward=None, streak=None, items=None):
    return {"metrics": {
        "balance": metric("points", after if after is not None else before,
                          before=before, after=after,
                          delta=after - before if before is not None and after is not None else None),
        "reward": metric("points", reward), "streak": metric("days", streak)},
        "items": items or []}


def domestic(context, client, journal, read_only=False):
    before = after = reward = streak = None
    checkin, reward_state, balance = "unknown", "unknown", "unknown"

    def finish(reason, execution="ok"):
        return result(context, execution, reason,
            {"checkin": checkin, "reward": reward_state, "balance": balance},
            details(before, after, reward, streak))

    def observe(state):
        nonlocal checkin, reward, reward_state, streak
        streak = state["streak"]
        if state["active"] is False:
            checkin = reward_state = "not_applicable"
        elif state["checked"] is True:
            checkin = "complete"
            reward = state["reward"] if state["reward"] is not None else journal.value.get("reward")
            reward_state = "complete" if reward is not None else "unknown"
            journal.set("complete", reward)

    try:
        state = client.status()
        observe(state)
        before = client.points()
        if checkin in {"complete", "not_applicable"} or journal.status != "unknown" or read_only:
            after, balance = before, "complete"
            reason = ("activity_inactive" if checkin == "not_applicable" else
                      "checkin_confirmed" if checkin == "complete" else
                      "checkin_not_requested" if read_only else "checkin_submission_unconfirmed")
            return finish(reason)
        journal.set("pending")
        write_error = None
        claimed = None
        try:
            claimed = client.checkin()
        except WorkBuddyError as error:
            write_error = error.reason
        # A failed/ambiguous write is reconciled only by reads, including on later runs.
        observe(client.status())
        if checkin == "complete" and reward is None and isinstance(claimed, dict) and boolean(claimed.get("success")) is not False:
            reward = amount(claimed.get("credit", field(claimed, "today_credit", "todayCredit")))
            reward_state = "complete" if reward is not None else "unknown"
            if reward is not None:
                journal.set("complete", reward)
        after, balance = client.points(), "complete"
        return finish("checkin_confirmed" if checkin == "complete" else
                      write_error or "checkin_submission_unconfirmed")
    except WorkBuddyError as error:
        return finish(error.reason, "failed")


def international(context, client, journal, read_only=False):
    before = after = None
    activity = "complete" if journal.status == "complete" else "unknown"
    reason = "activity_not_requested" if read_only else "activity_submission_unconfirmed"
    execution = "ok"
    try:
        before = client.points()  # Validate authentication before any paid activity.
        if journal.status == "unknown" and not read_only:
            journal.set("pending")
            try:
                client.active()
                activity = "complete"
                journal.set("complete")
            except WorkBuddyError as error:
                reason, execution = error.reason, "failed"
            after = client.points()
        else:
            after = before
        if activity == "complete" and execution == "ok":
            reason = "activity_sent_reward_unconfirmed"
    except WorkBuddyError as error:
        reason, execution = error.reason, "failed"
    return result(context, execution, reason,
        {"checkin": "not_applicable", "activity": activity, "reward": "unknown",
         "balance": "complete" if after is not None else "unknown"},
        details(before, after, items=[
            {"id": "active_request", "name": "国际版每日活跃请求", "status": activity,
             "reason": "active_request_confirmed" if activity == "complete" else "active_request_unconfirmed"},
            {"id": "active_reward", "name": "国际版活跃奖励到账", "status": "unknown",
             "reason": "active_reward_not_verified"}]))


def execute(context, edition, credentials, directory, *, read_only=False, transport=None):
    client = Client(edition, credentials.session, credentials.save, transport=transport)
    journal = Journal(context, directory, edition, client.session["uid"])
    return (domestic if edition == "cn" else international)(context, client, journal, read_only)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", choices=("cn", "intl"), required=True)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    context = {key: os.environ["BENEFITS_" + key.upper()]
               for key in ("run_id", "platform", "account", "business_date")}
    try:
        configured = os.environ.get("WORKBUDDY_CONFIG")
        if not configured:
            raise WorkBuddyError("missing_session")
        path = credential_path(configured)
        with Lease(path.with_name(path.name + ".lock")):
            credentials = Credentials(path, args.edition)
            output = execute(context, args.edition, credentials, os.environ["BENEFITS_STATE_DIR"],
                             read_only=args.status, transport=HTTP(os.environ.get("WORKBUDDY_PROXY")))
    except Busy:
        output = result(context, "busy", "credential_lock_busy")
    except WorkBuddyError as error:
        output = result(context, reason=error.reason)
    except (OSError, ValueError, TypeError):
        output = result(context, reason="configuration_or_io_error")
    atomic_json(os.environ["BENEFITS_RESULT_PATH"], output)
    return 0  # The common runner derives the exit code from the structured result.


if __name__ == "__main__":
    raise SystemExit(main())
