#!/usr/bin/env bash
set -euo pipefail
exec sudo -n -u yuwk /usr/bin/python3 -I /home/yuwk/cron/hermes/skysight_archive_read.py
