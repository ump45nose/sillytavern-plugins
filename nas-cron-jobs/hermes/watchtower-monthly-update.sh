#!/usr/bin/env bash
# The updater keeps detailed logs locally and emits only changes or failures.
set -euo pipefail
exec /usr/bin/python3 "$(dirname "$0")/watchtower_monthly_update.py"
