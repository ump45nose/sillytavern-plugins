#!/usr/bin/env bash
# Hermes Lingjun no-agent: business APIs run inside the app, not a Hermes agent.
set -euo pipefail
umask 027
cd /vol1/1000/Code/plaud-daily
exec /vol1/1000/Code/plaud-daily/.venv/bin/python \
  -m plaud_daily.daily_v3 \
  --config /vol1/1000/Code/plaud-daily/daily-v3.yaml \
  run-date --cron "$@"
