#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime=/home/yuwk/cron

install -d -m 0755 "$runtime/scripts" "$runtime/systemd" "$runtime/logs"
install -d -m 0700 "$runtime/env"
install -m 0644 "$repo_dir/README.md" "$runtime/README.md"
install -m 0644 "$repo_dir/INVENTORY.md" "$runtime/INVENTORY.md"

install -m 0755 "$repo_dir/hermes-env-audit/audit_env_base.py"   "$runtime/scripts/hermes-env-audit.py"
install -m 0755 "$repo_dir/hermes-telegram-recovery/hermes-telegram-recovery-check"   "$runtime/scripts/hermes-telegram-recovery-check"
install -m 0755 "$repo_dir/nas-container-boot/compose-autostart.sh"   "$runtime/scripts/compose-autostart.sh"
install -m 0755 "$repo_dir/nas-container-boot/container-boot.py"   "$runtime/scripts/container-boot.py"
install -m 0644 "$repo_dir/nas-container-boot/container-boot-order.txt"   "$runtime/scripts/container-boot-order.txt"
install -m 0755 "$repo_dir/qbittorrent-portmap-renew/qbittorrent-portmap-renew"   "$runtime/scripts/qbittorrent-portmap-renew"
install -m 0755 "$repo_dir/subboost-update/subboost-cron"   "$runtime/scripts/subboost-cron"
install -m 0755 "$repo_dir/taglab-delete-worker/delete_worker.py"   "$runtime/scripts/taglab-delete-worker.py"
install -m 0755 "$repo_dir/shellcrash-traffic/shellcrash_traffic.py"   "$runtime/scripts/shellcrash-traffic"
ln -sfn shellcrash-traffic "$runtime/scripts/shellcrash-traffic-report"
install -m 0755 "$repo_dir/shellcrash-traffic/export_ai_json.py"   "$runtime/scripts/shellcrash-traffic-ai-export"
install -m 0755 "$repo_dir/shellcrash-traffic/shellcrash-subboost-refresh.sh"   "$runtime/scripts/shellcrash-subboost-refresh"

find "$repo_dir" -mindepth 3 -maxdepth 3 -path '*/systemd/*' -type f -print0 |
  while IFS= read -r -d '' unit; do
    [[ $(basename "$unit") == apisix-auto-stop.* ]] && continue
    install -m 0644 "$unit" "$runtime/systemd/$(basename "$unit")"
  done

for unit in "$runtime/systemd/"*.service "$runtime/systemd/"*.timer; do
  [[ $(basename "$unit") == apisix-auto-stop.* ]] && continue
  sudo -n ln -sfn "$unit" "/etc/systemd/system/$(basename "$unit")"
done

sudo -n systemctl disable --now apisix-auto-stop.timer 2>/dev/null || true
sudo -n systemctl daemon-reload
sudo -n systemctl enable nas-container-boot.service shellcrash-traffic-collector.service >/dev/null

sudo -n systemctl enable --now    hermes-env-audit.timer   hermes-telegram-recovery.timer   qbittorrent-portmap-renew.timer   rsyslog-logrotate.timer   shellcrash-subboost-refresh.timer   shellcrash-traffic-ai-export.timer   shellcrash-traffic-report.timer   subboost-update-rule-index.timer   subboost-update-subscriptions.timer   taglab-delete-worker.timer >/dev/null

sudo -n systemctl restart shellcrash-traffic-collector.service

python3 "$repo_dir/deploy-hermes.py"

echo "Deployed host-native scheduled jobs from $repo_dir"
