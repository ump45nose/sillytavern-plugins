#!/usr/bin/env python3
"""Apply only presentation instructions to existing recurring model jobs."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys


def apply(jobs, policy, update):
    changed = []
    for job in jobs:
        if (job.get("name") not in policy["job_names"] or job.get("no_agent")
                or job.get("deliver") == "local" or (job.get("schedule") or {}).get("kind") == "once"):
            continue
        suffix = policy["prompt_suffix"]
        if suffix in job.get("prompt", ""):
            continue
        update(job["id"], {"prompt": job.get("prompt", "").rstrip() + "\n\n" + suffix})
        changed.append(job["name"])
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--profile-home", type=Path, default=Path("/home/hermes/.hermes/profiles/lingjun"))
    args = parser.parse_args()
    if not (args.profile_home / "cron/jobs.json").is_file():
        parser.error("existing profile cron store not found")
    os.environ["HERMES_HOME"] = str(args.profile_home)
    sys.path.insert(0, "/home/hermes/.hermes/hermes-agent")
    from cron.jobs import list_jobs, update_job
    from cron.scheduler_provider import resolve_cron_scheduler
    from hermes_constants import get_hermes_home
    policy = json.loads((Path(__file__).resolve().parents[1] / "model/notification-policy.json").read_text())
    jobs = list_jobs(include_disabled=True)
    if args.apply:
        backup = get_hermes_home() / "cron/migration-backups" / datetime.now().strftime("%Y%m%d-%H%M%S-notification-policy")
        backup.mkdir(mode=0o700)
        path = backup / "prompts.json"
        path.write_text(json.dumps({job["id"]: job.get("prompt", "") for job in jobs
                                    if job.get("name") in policy["job_names"]}, ensure_ascii=False))
        path.chmod(0o600)
        changed = apply(jobs, policy, update_job)
        if changed:
            resolve_cron_scheduler().on_jobs_changed()
    else:
        changed = apply(jobs, policy, lambda *_: None)
    print(json.dumps({"applied": args.apply, "jobs": changed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
