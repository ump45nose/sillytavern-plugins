#!/usr/bin/env bash
set -euo pipefail
umask 027
task_repo=$(cd "$(dirname "$0")/../.." && pwd)
cd "$task_repo"
exec "$task_repo/collectors/plaud/.venv/bin/python" \
  "$task_repo/agents/nas/plaud-process.py" \
  --config /home/yuwk/.config/personal-data-hub/plaud-processing.yaml \
  run-pending --cron "$@"
