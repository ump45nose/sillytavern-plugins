#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime=/home/yuwk/cron
[[ $# == 0 || ( $# == 1 && $1 == --check ) ]] || { echo "Usage: $0 [--check]" >&2; exit 2; }

files=(
  "0644|README.md|README.md"
  "0644|INVENTORY.md|INVENTORY.md"
  "0755|hermes-env-audit/audit_env_base.py|scripts/hermes-env-audit.py"
  "0755|hermes-telegram-recovery/hermes-telegram-recovery-check|scripts/hermes-telegram-recovery-check"
  "0755|nas-container-boot/compose-autostart.sh|scripts/compose-autostart.sh"
  "0755|nas-container-boot/container-boot.py|scripts/container-boot.py"
  "0644|nas-container-boot/container-boot-order.txt|scripts/container-boot-order.txt"
  "0755|qbittorrent-portmap-renew/qbittorrent-portmap-renew|scripts/qbittorrent-portmap-renew"
  "0755|subboost-update/subboost-cron|scripts/subboost-cron"
  "0755|taglab-delete-worker/delete_worker.py|scripts/taglab-delete-worker.py"
  "0755|shellcrash-traffic/shellcrash_traffic.py|scripts/shellcrash-traffic"
  "0755|shellcrash-traffic/export_ai_json.py|scripts/shellcrash-traffic-ai-export"
  "0755|shellcrash-traffic/shellcrash-subboost-refresh.sh|scripts/shellcrash-subboost-refresh"
  "0644|nas-container-boot/container-boot-ignore.txt|scripts/container-boot-ignore.txt"
)

# Validate every input before changing the runtime.
for entry in "${files[@]}"; do
  IFS="|" read -r mode source target <<< "$entry"
  [[ -f "$repo_dir/$source" ]] || { echo "Missing source: $source" >&2; exit 1; }
done
python3 "$repo_dir/deploy-hermes.py" --check
[[ ${1:-} != --check ]] || exit 0

install -d -m 0755 "$runtime/scripts" "$runtime/systemd" "$runtime/logs"
install -d -m 0700 "$runtime/env"

for entry in "${files[@]}"; do
  IFS="|" read -r mode source target <<< "$entry"
  install -m "$mode" "$repo_dir/$source" "$runtime/$target"
done
ln -sfn shellcrash-traffic "$runtime/scripts/shellcrash-traffic-report"

find "$repo_dir" -mindepth 3 -maxdepth 3 -path '*/systemd/*' -type f -print0 |
  while IFS= read -r -d '' unit; do
    [[ $(basename "$unit") == apisix-auto-stop.* || $(basename "$unit") == hermes-telegram-recovery.* ]] && continue
    install -m 0644 "$unit" "$runtime/systemd/$(basename "$unit")"
  done

for unit in "$runtime/systemd/"*.service "$runtime/systemd/"*.timer; do
  [[ $(basename "$unit") == apisix-auto-stop.* || $(basename "$unit") == hermes-telegram-recovery.* ]] && continue
  sudo -n ln -sfn "$unit" "/etc/systemd/system/$(basename "$unit")"
done

sudo -n systemctl disable --now apisix-auto-stop.timer hermes-telegram-recovery.timer 2>/dev/null || true
sudo -n systemctl daemon-reload
sudo -n systemctl enable nas-container-boot.service shellcrash-traffic-collector.service >/dev/null

sudo -n systemctl enable --now    hermes-env-audit.timer   qbittorrent-portmap-renew.timer   shellcrash-subboost-refresh.timer   shellcrash-traffic-ai-export.timer   shellcrash-traffic-report.timer   subboost-update-rule-index.timer   subboost-update-subscriptions.timer   taglab-delete-worker.timer >/dev/null

sudo -n systemctl restart shellcrash-traffic-collector.service

sudo -n bash "$repo_dir/nas-resource-governance/install.sh"

python3 "$repo_dir/deploy-hermes.py"

echo "Deployed host-native scheduled jobs from $repo_dir"
