#!/usr/bin/env bash
# Legacy action names follow the current persistent-container policy.
set -euo pipefail
case "${1:-}" in
  stop) mode=audit ;;
  start) mode=repair ;;
  *) echo 'container maintenance: expected start or stop' >&2; exit 2 ;;
esac
exec /home/hermes/.hermes/hermes-agent/venv/bin/python3 "$(dirname "$0")/container-maintenance.py" "$mode"
