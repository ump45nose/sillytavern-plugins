#!/usr/bin/env python3
"""Refresh once at cron execution. Empty stdout safely skips unreliable runs."""
import json
import os

from companion_runtime import config, current_context, database, history, operational_error


def main():
    try:
        if not config().get("enabled", False):
            return
        with database() as db:
            job_id = os.environ.get("HERMES_CRON_JOB_ID", "")
            row = db.execute("SELECT payload FROM events WHERE job_id=?", (job_id,)).fetchone()
            if row is None:
                raise RuntimeError("missing companion event")
            observed = history(db)
            # The cron prompt holds no frozen history, only this fresh single block.
            print(current_context(db, observed, event=json.loads(row[0]),
                                  budget=int(config().get("extra_context_tokens", 12000))))
    except Exception as exc:
        operational_error("pre_run skipped", exc)


if __name__ == "__main__":
    main()
