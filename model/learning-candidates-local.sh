#!/bin/sh
HERMES_ROOT="${HERMES_ROOT:-/home/hermes/.hermes}"
export HERMES_HOME="$HERMES_ROOT/profiles/lingjun"
export PYTHONPATH="/home/hermes/.hermes/hermes-agent${PYTHONPATH:+:$PYTHONPATH}"
exec /home/hermes/.hermes/hermes-agent/venv/bin/python \
  "$(dirname "$0")/learning_candidates.py" \
  --root "$HERMES_ROOT" --limit 50 "$@"
