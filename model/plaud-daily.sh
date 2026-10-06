#!/usr/bin/env bash
# Hermes Lingjun no-agent: business APIs run inside the app, not a Hermes agent.
set -euo pipefail
umask 027
cd /home/yuwk/code/personal-data-hub/legacy/plaud
exec /home/yuwk/code/personal-data-hub/legacy/plaud/.venv/bin/python \
  -m plaud_daily.daily_v3 \
  --config /home/yuwk/code/personal-data-hub/legacy/plaud/daily-v3.yaml \
  run-date --cron "$@"
