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

Hermes deterministic task code and report modules are deployed to
`/home/yuwk/cron/hermes`. Tasks that call a model or schedule model work live in
`/home/yuwk/cron/model`. `retired/` preserves disabled legacy container wrappers.
Hermes still owns task scheduling and delivery state.

`/etc/systemd/system` contains symlinks only. Custom host scheduling uses
systemd timers; user crontabs are intentionally kept empty unless an
application owns and rewrites them itself.

## Managed jobs

- `apisix-auto-stop`: retired; the timer stays disabled because Hermes uses
  APISIX as its persistent model entrypoint.
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

## Deploy Hermes cron code

Run `python3 deploy-hermes.py` for the Hermes source migration alone. This
does not restart gateways, run business jobs or change their schedules.
`deploy.sh` also installs these sources during a full host deployment.

Hermes restricts executable cron paths to each profile's `scripts/` directory.
The installer preserves that boundary with small Python/Bash entrypoints which
forward to the canonical source under `/home/yuwk/cron`. It also forwards the
Episode/candidate CLI and Personal Review cron entrypoints, backing up each
previous file under the private profile runtime.

Create `/home/yuwk/cron/env/hermes.local.json` from
`hermes/local.example.json` and fill in local routing/identity values. Keep the
directory private and grant only the Hermes runtime account traversal of the
directory and read access to this file. Do not commit the local file. Provider
keys remain in the Hermes root `.env`; OAuth tokens remain in the profile's
`mcp-tokens/` directory. Email cron uses the profile's `email` MCP OAuth cache;
complete `hermes mcp login email` as the Hermes runtime account in the Lingjun
profile once. Cron refreshes cached tokens and fails promptly when login is
required. It never launches interactive authorization.

`hermes/schedules.json` and `model/schedules.json` contain a sanitized inventory,
without prompts, chat IDs, credentials, execution history or generated one-shot
context. Runtime `jobs.json`, databases, outputs and backups are not uploaded.

The applied scheduler heartbeat change is retained in
`hermes/runtime-patches/cron-heartbeat.patch`. It lets the atomic owner-checked
heartbeat continue while a network delivery holds the per-job side-effect
fence. Apply it to the existing Hermes checkout when restoring this deployment;
the source migration installer does not automatically patch the framework.
