#!/usr/bin/env bash
set -euo pipefail
source /home/yuwk/cron/env/plaud-archive.env
exec "$PLAUD_PYTHON" -m plaud_archive.cli --config "$PLAUD_CONFIG" run-due "$@"
