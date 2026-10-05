# NAS cron jobs

This repository is the source of truth for host-native scheduled jobs on the NAS.

## Layout

Each managed job owns one top-level directory. A job may contain:
- executable source;
- systemd service/timer units;
- a README or environment example.

Deployment copies executable files to `/home/yuwk/cron/scripts`, units to
`/home/yuwk/cron/systemd`, and keeps machine-local secrets under
`/home/yuwk/cron/env`.

`/etc/systemd/system` contains symlinks only. Custom host scheduling uses
systemd timers; user crontabs are intentionally kept empty unless an
application owns and rewrites them itself.

## Managed jobs

- `apisix-auto-stop`: check APISIX every 10 minutes and stop it after one hour.
- `hermes-env-audit`: daily shared-secret placement audit for Hermes profiles.
- `hermes-telegram-recovery`: two-minute Telegram polling recovery check.
- `nas-container-boot`: ordered NAS container startup after Docker starts.
- `qbittorrent-portmap-renew`: hourly qBittorrent UPnP mapping renewal.
- `rsyslog-logrotate`: rotate rsyslog files every 30 minutes.
- `shellcrash-traffic`: traffic collector, reports, AI JSON and SubBoost refresh.
- `subboost-update`: subscription refresh every six minutes and rule index hourly.
- `taglab-delete-worker`: music cleanup every five minutes.

## Intentionally external schedulers

These are inventoried but not migrated because they are owned by the OS or by
the application itself:

- Debian/FNOS timers and cron files: apt, dpkg, logrotate, man-db, fstrim,
  e2scrub, sysstat, mdmonitor and related package jobs.
- ShellCrash root crontab entries maintained by ShellCrash itself.
- Hermes profile cron state under `~hermes/.hermes/profiles/*/cron`.
- Container-native schedulers such as Watchtower, qbit_manage and Navidrome.
- Application-internal schedules such as Personal CRM reminders/chat events.

See `INVENTORY.md` for the current scheduler map.
