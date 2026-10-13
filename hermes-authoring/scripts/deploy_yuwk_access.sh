#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
SOURCE_ROOT="$(dirname -- "$SCRIPT_DIR")"
READY_FILE="/run/hermes-yuwk-access/ready"

getent group hermes-readers >/dev/null
getent passwd yuwk >/dev/null
getent passwd hermes >/dev/null

sudo install -o root -g root -m 0755 \
  "$SOURCE_ROOT/scripts/hermes_yuwk_access_acl.py" \
  /usr/local/sbin/hermes-yuwk-access
sudo install -o root -g root -m 0644 \
  "$SOURCE_ROOT/systemd/hermes-yuwk-access.service" \
  /etc/systemd/system/hermes-yuwk-access.service

sudo usermod -a -G hermes-readers yuwk
sudo usermod -a -G hermes yuwk

previous_ready="$(sudo cat "$READY_FILE" 2>/dev/null || true)"
sudo systemctl disable --now hermes-readonly-acl.service 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable hermes-yuwk-access.service
sudo systemctl restart hermes-yuwk-access.service

for _ in $(seq 1 120); do
  current_ready="$(sudo cat "$READY_FILE" 2>/dev/null || true)"
  if [[ -n "$current_ready" && "$current_ready" != "$previous_ready" ]]; then
    break
  fi
  sleep 1
done

sudo test -s "$READY_FILE"
sudo systemctl is-active --quiet hermes-yuwk-access.service
sudo cat "$READY_FILE"
