#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime=/home/yuwk/cron

install -d -m 0755 "$runtime/scripts" "$runtime/systemd" "$runtime/logs"
install -d -m 0700 "$runtime/env"

install -m 0755 "$repo_dir/taglab-delete-worker/delete_worker.py"   "$runtime/scripts/taglab-delete-worker.py"

install -m 0755 "$repo_dir/shellcrash-traffic/shellcrash_traffic.py"   "$runtime/scripts/shellcrash-traffic"
ln -sfn shellcrash-traffic "$runtime/scripts/shellcrash-traffic-report"
install -m 0755 "$repo_dir/shellcrash-traffic/export_ai_json.py"   "$runtime/scripts/shellcrash-traffic-ai-export"
install -m 0755 "$repo_dir/shellcrash-traffic/shellcrash-subboost-refresh.sh"   "$runtime/scripts/shellcrash-subboost-refresh"

for unit in "$repo_dir/taglab-delete-worker/systemd/"*             "$repo_dir/shellcrash-traffic/systemd/"*; do
  install -m 0644 "$unit" "$runtime/systemd/$(basename "$unit")"
done

for unit in   taglab-delete-worker.service   taglab-delete-worker.timer   shellcrash-traffic-collector.service   shellcrash-traffic-report.service   shellcrash-traffic-report.timer   shellcrash-traffic-ai-export.service   shellcrash-traffic-ai-export.timer   shellcrash-subboost-refresh.service   shellcrash-subboost-refresh.timer; do
  sudo -n ln -sfn "$runtime/systemd/$unit" "/etc/systemd/system/$unit"
done

sudo -n systemctl daemon-reload
sudo -n systemctl enable --now   taglab-delete-worker.timer   shellcrash-traffic-report.timer   shellcrash-traffic-ai-export.timer   shellcrash-subboost-refresh.timer
sudo -n systemctl restart shellcrash-traffic-collector.service

echo "Deployed cron jobs from $repo_dir"
