#!/usr/bin/env bash
# Routine scheduled transitions are silent; failures alone reach Telegram.
set -u

action="${1:-}"
stack="${2:-}"
if [[ -z "$action" || -z "$stack" ]]; then
  printf 'container schedule wrapper: missing action/stack\n' >&2
  exit 2
fi

output=$(/vol2/1000/Docker/scripts/container-schedule.sh "$action" "$stack" 2>&1)
status=$?
if (( status != 0 )); then
  printf '%s\n' "$output" >&2
  exit "$status"
fi
exit 0
