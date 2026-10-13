#!/usr/bin/env bash
# Current persistent deployment: audit or repair the canonical boot plan.
set -euo pipefail
exec /home/hermes/.hermes/hermes-agent/venv/bin/python3 "$(dirname "$0")/container-maintenance.py" repair
