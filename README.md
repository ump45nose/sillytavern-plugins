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
`/home/yuwk/cron/model`. `retired/` preserves historical container wrappers.
Hermes still owns task scheduling and delivery state.

PLAUD three-source v3 uses `model/plaud-daily.sh`, forwarded by the Lingjun
profile's trusted `scripts/plaud-daily.sh`. Its no-agent schedule is
`*/30 0-7 * * *` (Asia/Taipei): synchronize and prepare all previous-day
recordings, then at/after 07:30 send one complete, validated daily Markdown
to CPA Grok. App settings, credentials and isolated business state remain in
the PLAUD app; no keys or runtime job records belong in this repository.

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
- `steam-asf`: pinned ASF/FreePackages deployment and private terminal login;
  Steam read-only execution is scheduled through Hermes after account acceptance.

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
`mcp-tokens/` directory. Email cron defaults to the profile's `email` MCP OAuth
cache and never launches interactive authorization. On this host,
`email_transport=hub-local-readonly` reuses Personal Data Hub's existing local
read-only bridge and email container, without copying account credentials or
OAuth caches. Both clients normalize MCP 1.x/2.x result fields.

Health cron readers use `health_api_url` and an existing viewer token file when
configured, including the Personal Review health source. They paginate bounded
time windows and report failures rather than falling back to stale SQLite.
Legacy SQLite remains supported on hosts without a configured hub. The token
stays outside this repository; this NAS requires group `hermes`, mode 0640 for
the existing viewer token because named ACL alone did not allow runtime reads.
Set `ha_url` and `npm_health_url` to the actual listener addresses in private
configuration. The probes bypass outbound proxies for these local services.
Set `moviepilot_api_base` to MoviePilot's actual private IP listener, including
`/api/v1`; a LAN-only port binding cannot be reached through `127.0.0.1`.
The report does not follow redirects or forward its API credential elsewhere.

The six former container stop/start schedules use `container-maintenance.py`:
former stop/enforcement times audit the persistent boot plan; former start
times start stopped entries in dependency order. They leave unlisted containers
alone. A failed readiness observation is confirmed up to three times before
reporting an unavailable container. Generic review prompt templates are in `model/review-prompts.json`;
installing them into the private scheduler remains an explicit maintenance step.

Episode extraction reports pending backlog separately from failed processing.
A bounded run with pending work and no actual failures exits successfully;
failed extraction or memory writes still produce a nonzero exit status.
The extractor has its own 180-second request timeout in the Hermes runtime;
changing only the profile's auxiliary timeout does not change that bound.

`benefits-aliyun` was paused at the user's request on 2026-10-08 because its
CookieCloud login expires too frequently. The schedule inventory records it
disabled; redeployment must preserve the paused live job.
The private deployment task also has `enabled: false`: the launcher skips it,
the daily summary labels it disabled, and the exception report excludes it.
Its historical result is retained.

`welfare_monitor.py` persists per-host HTTP 429 cooldowns in its existing
private SQLite state. It honors Retry-After, defaults to one hour when absent
or invalid, and waits at least one minute; other feeds on that host skip their
requests while the cooldown applies. It keeps the existing cookies and proxy.
Successful source probes do not mark unseen items as delivered. On 2026-10-08
the two Linux.do feeds were readable again (100 and 30 items); this observation
does not imply future rate limits have been eliminated.

`hermes/schedules.json` and `model/schedules.json` contain a sanitized inventory,
without prompts, chat IDs, credentials, execution history or generated one-shot
context. Runtime `jobs.json`, databases, outputs and backups are not uploaded.

The applied scheduler heartbeat change is retained in
`hermes/runtime-patches/cron-heartbeat.patch`. It lets the atomic owner-checked
heartbeat continue while a network delivery holds the per-job side-effect
fence. Apply it to the existing Hermes checkout when restoring this deployment;
the source migration installer does not automatically patch the framework.

嘉颖陪伴 cron 的素材来源、连续生活状态、30 天历史与选择性部署说明见 [hermes/COMPANION.md](hermes/COMPANION.md)。
