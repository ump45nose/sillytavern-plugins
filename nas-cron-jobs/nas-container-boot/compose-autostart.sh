#!/usr/bin/env bash
set -euo pipefail

LOG_FILE=/home/yuwk/cron/logs/container-boot.log
mkdir -p "$(dirname "$LOG_FILE")"
exec >>"$LOG_FILE" 2>&1

echo "==== $(date -Is) ordered container boot begin ===="
python3 /home/yuwk/cron/scripts/container-boot.py
echo "==== $(date -Is) ordered container boot end ===="
