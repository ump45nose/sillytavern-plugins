#!/bin/sh
HERMES_ROOT="${HERMES_ROOT:-/home/hermes/.hermes}"
export HERMES_HOME="$HERMES_ROOT/profiles/lingjun"
export PYTHONPATH="/home/hermes/.hermes/hermes-agent${PYTHONPATH:+:$PYTHONPATH}"
exec /home/hermes/.hermes/hermes-agent/venv/bin/python \
  "$(dirname "$0")/episode_daily.py" \
  --root "$HERMES_ROOT" \
  --backfill-since 2026-07-30T22:24:00+08:00 \
  --max-segments 50 \
  --max-seconds 1200
