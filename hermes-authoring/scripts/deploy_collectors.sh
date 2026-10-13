#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTOR_SOURCE="$SOURCE_DIR/collectors"
LINGJUN_HOME="/home/hermes/.hermes/profiles/lingjun"
TARGET_DIR="$LINGJUN_HOME/scripts"
JOBS_FILE="$LINGJUN_HOME/cron/jobs.json"
PYTHON="/home/hermes/.hermes/hermes-agent/venv/bin/python"
HERMES="/home/hermes/.hermes/hermes-agent/venv/bin/hermes"
HERMES_TMP="/home/hermes/.hermes/tmp"

sudo install -d -m 0750 -o hermes -g hermes "$HERMES_TMP"
sudo -n -u hermes env TMPDIR="$HERMES_TMP" PYTHONDONTWRITEBYTECODE=1 \
  "$PYTHON" -c \
  'import sys; [compile(open(path, encoding="utf-8").read(), path, "exec") for path in sys.argv[1:]]' \
  "$COLLECTOR_SOURCE/shared_state_collector.py" \
  "$COLLECTOR_SOURCE/collect_containers.py" \
  "$COLLECTOR_SOURCE/collect_environment.py"

sudo install -d -m 0750 -o hermes -g hermes "$TARGET_DIR"
for collector in \
  shared_state_collector.py \
  collect_containers.py \
  collect_environment.py
do
  sudo install -m 0750 -o hermes -g hermes \
    "$COLLECTOR_SOURCE/$collector" "$TARGET_DIR/$collector"
done

sudo -n -u hermes env HERMES_HOME="$LINGJUN_HOME" \
  "$PYTHON" "$TARGET_DIR/collect_containers.py"
sudo -n -u hermes env HERMES_HOME="$LINGJUN_HOME" \
  "$PYTHON" "$TARGET_DIR/collect_environment.py"

job_id_by_name() {
  local name="$1"
  sudo -n -u hermes "$PYTHON" - "$JOBS_FILE" "$name" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    jobs = json.load(handle).get("jobs", [])
for job in jobs:
    if job.get("name") == sys.argv[2]:
        print(job["id"])
        break
PY
}

ensure_job() {
  local name="$1"
  local schedule="$2"
  local script="$3"
  local job_id
  job_id="$(job_id_by_name "$name")"
  if [[ -n "$job_id" ]]; then
    sudo -n -u hermes env HERMES_HOME="$LINGJUN_HOME" \
      "$HERMES" cron edit "$job_id" \
      --schedule "$schedule" \
      --script "$script" \
      --no-agent \
      --deliver local >/dev/null
  else
    sudo -n -u hermes env HERMES_HOME="$LINGJUN_HOME" \
      "$HERMES" cron create "$schedule" \
      --name "$name" \
      --script "$script" \
      --no-agent \
      --deliver local >/dev/null
  fi
}

ensure_job "shared-state-container-inventory" "*/15 * * * *" \
  "collect_containers.py"
ensure_job "shared-state-host-environment" "7 * * * *" \
  "collect_environment.py"

echo "shared-state collectors deployed and cron jobs reconciled"
