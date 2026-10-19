#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
runtime=/home/yuwk/cron

install -m 0755 "$source_dir/resource-snapshot.py" "$runtime/scripts/nas-resource-history.py"
for unit in nas-resource-history.service nas-resource-history.timer; do
    install -m 0644 "$source_dir/systemd/$unit" "$runtime/systemd/$unit"
    sudo -n ln -sfn "$runtime/systemd/$unit" "/etc/systemd/system/$unit"
done
sudo -n install -d -m 0755 /etc/systemd/journald.conf.d /etc/systemd/system/sysstat-collect.timer.d
sudo -n install -m 0644 "$source_dir/journald.conf" /etc/systemd/journald.conf.d/nas-resource-history.conf
sudo -n install -m 0644 "$source_dir/sysstat-timer.conf" /etc/systemd/system/sysstat-collect.timer.d/nas-resource-history.conf
sudo -n install -m 0644 "$source_dir/logrotate.conf" /etc/logrotate.d/nas-resource-history
sudo -n sed -i 's/^ENABLED=.*/ENABLED="true"/' /etc/default/sysstat
sudo -n sed -i 's/^SADC_OPTIONS=.*/SADC_OPTIONS="-S XALL"/; s/^COMPRESSAFTER=.*/COMPRESSAFTER=3/' /etc/sysstat/sysstat
sudo -n mkdir -p /var/log/journal
sudo -n systemd-tmpfiles --create --prefix /var/log/journal
sudo -n systemctl daemon-reload
sudo -n systemctl restart systemd-journald.service
sudo -n journalctl --flush
sudo -n systemctl enable --now sysstat.service sysstat-collect.timer sysstat-summary.timer nas-resource-history.timer
sudo -n systemctl restart sysstat-collect.timer
sudo -n systemctl start sysstat-collect.service nas-resource-history.service
