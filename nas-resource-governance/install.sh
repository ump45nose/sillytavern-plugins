#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo "Run with sudo" >&2; exit 1; }
src=$(cd "$(dirname "$0")" && pwd)
backup=/var/backups/nas-resource-governance/services-$(date +%Y%m%d-%H%M%S)
install -d -m 0700 "$backup"
put() {
  local from=$1 to=$2 owner=$3 mode=${4:-0644}
  cmp -s "$from" "$to" && return 0
  if [[ -e "$to" ]]; then
    install -d "$backup$(dirname "$to")"
    cp -p "$to" "$backup$to"
  fi
  install -d "$(dirname "$to")"
  install -o "$owner" -g "$(id -gn "$owner")" -m "$mode" "$from" "$to"
}
userctl() {
  local name=$1 uid=$2; shift 2
  runuser -u "$name" -- env XDG_RUNTIME_DIR=/run/user/"$uid" DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"$uid"/bus systemctl --user "$@"
}
codex_changed=0; hermes_changed=0; journal_changed=0
cmp -s "$src/config/codex-agent.service" /home/yuwk/.config/systemd/user/codex-agent.service || codex_changed=1
cmp -s "$src/hermes_scope.py" /home/hermes/.hermes/hermes-agent/tools/local_resource_scope.py || hermes_changed=1
cmp -s "$src/config/journald.conf" /etc/systemd/journald.conf.d/nas-agents.conf || journal_changed=1
put "$src/codex-entry.py" /home/yuwk/.local/lib/nas-agent/codex yuwk 0755
put "$src/hermes_scope.py" /home/hermes/.hermes/hermes-agent/tools/local_resource_scope.py hermes
put "$src/config/codex-agent.service" /home/yuwk/.config/systemd/user/codex-agent.service yuwk
put "$src/config/codex.slice" /home/yuwk/.config/systemd/user/codex.slice yuwk
put "$src/config/chromium-scope.conf" /home/yuwk/.config/systemd/user/app-org.chromium.Chromium-.scope.d/50-codex-budget.conf yuwk
put "$src/config/hermes-user.conf" /etc/systemd/system/user-988.slice.d/50-nas-resource.conf root
put "$src/config/nascontainers.slice" /etc/systemd/system/nascontainers.slice root
put "$src/config/logrotate.timer.conf" /etc/systemd/system/logrotate.timer.d/50-nas-single-owner.conf root
put "$src/config/journald.conf" /etc/systemd/journald.conf.d/nas-agents.conf root
put "$src/config/sysstat.timer.conf" /etc/systemd/system/sysstat-collect.timer.d/50-nas-minute.conf root
for profile in lingjun companion; do
  put "$src/config/hermes-resource.conf" /home/hermes/.config/systemd/user/hermes-gateway-$profile.service.d/50-nas-resource.conf hermes
done
install -d -o yuwk -g "$(id -gn yuwk)" -m 0700 /home/yuwk/.config/nas-resource-governance
proxy=/home/yuwk/.config/nas-resource-governance/codex.env
[[ -e "$proxy" ]] || install -o yuwk -g "$(id -gn yuwk)" -m 0600 /dev/null "$proxy"
if ! grep -Fq '# >>> NAS Codex service >>>' /home/yuwk/.bashrc; then
  install -d "$backup/home/yuwk"
  cp -p /home/yuwk/.bashrc "$backup/home/yuwk/.bashrc"
  cat >> /home/yuwk/.bashrc <<'PROFILE'

# >>> NAS Codex service >>>
export CODEX_INSTALL_DIR='/home/yuwk/.local/lib/nas-agent'
export PATH="/home/yuwk/.local/lib/nas-agent:$PATH"
# <<< NAS Codex service <<<
PROFILE
fi
systemctl daemon-reload
systemctl restart logrotate.timer
[[ $journal_changed == 0 ]] || systemctl restart systemd-journald
userctl yuwk 1000 daemon-reload
userctl hermes 988 daemon-reload
userctl yuwk 1000 enable --now codex-agent.service
[[ $codex_changed == 0 ]] || userctl yuwk 1000 restart codex-agent.service
if [[ $hermes_changed == 1 ]]; then
  for profile in lingjun companion; do
    userctl hermes 988 kill --kill-who=main --signal=SIGUSR1 hermes-gateway-$profile.service
  done
fi
echo "Installed native service budgets; backup: $backup"
