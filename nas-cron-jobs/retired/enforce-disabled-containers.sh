#!/usr/bin/env bash
# Expected absent/already-down entries are normal. Only corrections and hard
# errors are delivered; the full audit remains in the underlying log.
set -u
output=$(/vol2/1000/Docker/scripts/enforce-disabled-containers.sh "$@" 2>&1)
status=$?
interesting=$(printf '%s\n' "$output" | grep -E '\] (FIX|STOP|RM|ERROR)' || true)
if [[ -n "$interesting" ]]; then
  printf '%s\n' "$interesting"
fi
if (( status != 0 )) || grep -q '\] ERROR' <<<"$output"; then
  exit 1
fi
exit 0
