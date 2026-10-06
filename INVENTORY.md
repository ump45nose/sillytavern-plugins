# Scheduler inventory

## Canonical host jobs

| Job | Scheduler | Schedule |
| --- | --- | --- |
| APISIX auto-stop | retired, disabled | formerly every 10 minutes |
| Hermes env audit | systemd timer | daily 06:17 |
| Hermes Telegram recovery | systemd timer | every 2 minutes |
| qBittorrent port mapping | systemd timer | hourly |
| ShellCrash → SubBoost refresh | systemd timer | hourly with jitter |
| ShellCrash AI JSON | systemd timer | hourly at :17 |
| ShellCrash HTML report | systemd timer | daily around 08:15 |
| SubBoost subscriptions | systemd timer | every 6 minutes |
| SubBoost rule index | systemd timer | hourly |
| TagLab delete worker | systemd timer | every 5 minutes |
| rsyslog rotate | systemd timer | every 30 minutes |
| NAS container boot | systemd service | on Docker startup |
| ShellCrash traffic collector | systemd service | continuous |

All files above are sourced from this repository and deployed under
`/home/yuwk/cron`.

## Application-managed schedules

### ShellCrash root crontab
ShellCrash owns two root crontab entries:
- save dashboard/runtime config every 10 minutes;
- Telegram bot watchdog every minute.

Do not copy these into this repository. ShellCrash may rewrite them.

### Hermes
Hermes owns its scheduler database and `jobs.json` beneath
`/home/hermes/.hermes/profiles/*/cron`. It must remain application-managed.
Concrete code is sourced from `hermes/` and `model/` in this repository and
deployed to the matching directories under `/home/yuwk/cron`. Trusted profile
entrypoints call that code. See the sanitized schedule inventories in both
directories. Six obsolete container start/stop/enforcement tasks are paused;
persistent containers use the boot service and Docker restart policies.

### Containers
Known container-native schedulers include:
- Watchtower: daily update schedule inside container configuration;
- qbit_manage: interval configured by `QBT_SCHEDULE`;
- Navidrome: library scan schedule via `ND_SCANSCHEDULE`;
- Personal CRM: reminder and chat-event loops inside the application.

## OS/vendor schedules

Leave Debian/FNOS jobs in their package-owned paths:
- `/etc/crontab`;
- `/etc/cron.d`;
- `/etc/cron.daily|weekly|monthly`;
- units under `/lib/systemd/system`.

They include apt, dpkg, logrotate, exim, man-db, quota, samba, sysstat,
fstrim, e2scrub and mdmonitor jobs.
