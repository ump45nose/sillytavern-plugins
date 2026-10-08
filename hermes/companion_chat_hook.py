#!/usr/bin/env python3
"""pre_llm_call context restricted to Lingjun owner's companion Telegram topic."""
import json
import os
import sys

from companion_runtime import PROFILE, config, current_context, database, history, operational_error, scoped_session


def main():
    try:
        value = json.load(sys.stdin)
        extra = value.get("extra") or {}
        if (value.get("hook_event_name") != "pre_llm_call" or not config().get("enabled", False)
                or os.environ.get("HERMES_HOME") != str(PROFILE)
                or not scoped_session(value.get("session_id", ""))
                or extra.get("platform") not in (None, "telegram")
                or str(extra.get("sender_id") or config()["user_id"]) != config()["user_id"]):
            print("{}"); return
        with database() as db:
            observed = history(db)
            context = current_context(db, observed, budget=2000, history_budget=1300,
                                      current_user=extra.get("user_message"))
            # Shell-hook bridge spills output above 10,000 chars; stay well below it.
            print(json.dumps({"context": context[:8000]}, ensure_ascii=False))
    except Exception as exc:
        operational_error("chat_hook", exc)
        print("{}")


if __name__ == "__main__":
    main()
