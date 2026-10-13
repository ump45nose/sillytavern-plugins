#!/usr/bin/env bash
# Queue one same-day retry only when the 22:00 primary run did not succeed.
set -euo pipefail

jobs=/home/hermes/.hermes/profiles/lingjun/cron/jobs.json
job_id=4edbceb0e2a8
today=$(TZ=Asia/Shanghai date +%F)
row=$(jq -r --arg id "$job_id" '.jobs[] | select(.id == $id) | [(.last_status // ""), (.last_run_at // "")] | @tsv' "$jobs")
status=${row%%$'\t'*}
last_run=${row#*$'\t'}
if [[ "$status" == "ok" && "$last_run" == "$today"* ]]; then
  exit 0
fi

HERMES_HOME=/home/hermes/.hermes/profiles/lingjun \
  /home/hermes/.hermes/hermes-agent/venv/bin/hermes cron run "$job_id" >/dev/null
printf '%s\n' '- Mem0：同步未成功，已安排重试'
