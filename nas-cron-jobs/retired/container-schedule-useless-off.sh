#!/usr/bin/env bash
# container-schedule-useless-off.sh - 迁移自 /etc/cron.d/container-schedule
exec /home/hermes/.hermes/profiles/lingjun/scripts/container-schedule-quiet.sh stop useless-off
