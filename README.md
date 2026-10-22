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

Plaud Archive's wrapper is `model/plaud-daily.sh`, forwarded by Lingjun's trusted
`scripts/plaud-daily.sh`. It reads the private `PLAUD_PYTHON` and `PLAUD_CONFIG`
paths in `/home/yuwk/cron/env/plaud-archive.env`; business code lives in
`personal-info/plaud-archive/`. The existing job stays paused until archive
acceptance and an explicit scheduler cutover; deploying source does not resume it.
See [host entry](plaud-archive/README.md) for the native service.

Scheduled-job units link from `/etc/systemd/system` to their runtime copies.
Agent budgets and native logging configuration are installed directly by
`nas-resource-governance/install.sh`. Custom host scheduling uses systemd timers;
user crontabs are intentionally empty unless an application owns them.

## Managed jobs

- `apisix-auto-stop`: retired; the timer stays disabled because Hermes uses
  APISIX as its persistent model entrypoint.
- `hermes-env-audit`: daily shared-secret placement audit for Hermes profiles.
- `hermes-telegram-recovery`: retired, disabled; native Hermes adapter
  reconnection replaces the old whole-gateway restart timer.
- `nas-container-boot`: ordered NAS container startup after Docker starts.
- `nas-resource-governance`: native budgets: Codex total 3 GiB, Hermes user total
  3 GiB, selected containers total 6 GiB. Deploy with
  `sudo bash nas-resource-governance/install.sh`. Services use group OOM cleanup
  and limited native restarts; logs use journal, Docker and sysstat.
- `qbittorrent-portmap-renew`: hourly qBittorrent UPnP mapping renewal.
- `rsyslog-logrotate`: retired; the native global logrotate timer covers it every 30 minutes.
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

### Notification presentation

Human-facing notifications use Markdown short headings and bullet lists, without
execution narration, debug paths, repeated labels, empty sections or full state
dumps. Notice-bot messages reuse Hermes' installed Telegram MarkdownV2 formatter
and UTF-16-aware splitter; bot identity and topic receipt verification remain
mandatory. Error codes, links and code spans retain their literal contents.

Favsync emits only `- platform: problem` for current issues, grouped and
deduplicated by platform. Execution history remains in its source state and is
not repeated after recovery. Benefits remain exception-only reports.
Disabled tasks stay disabled, including Aliyun.

The media report includes download events and watchlist/theme business changes
since its previous successful report. Download submissions use their event times
(24 hours on first run); refreshed timestamps alone do not prove a state change.
State records and plugin APIs use an observed business-field baseline, so the
first observation does not call old tasks new. Unchanged tasks, empty categories, release filenames and full plugin
snapshots are omitted. No changes means no message. The private checkpoint is
`~hermes/.hermes/profiles/lingjun/cron/report-state/media-automation.json`, using
the profile's existing private ACL and runtime identity;
only confirmed delivery, or a successful empty baseline run, advances it.
Failed API reads retain that plugin's prior baseline. Intermediate transitions
between observations cannot be reconstructed and are not invented. Running
`media_automation_daily_report.py` previews without advancing the checkpoint.

Episode details remain in its private `cron/output/episode-daily-latest.json`;
the notification contains results, pending work and failures. `--json` retains
machine-readable diagnostics. Learning candidates retain their exact approval
and rejection commands and delivery receipts. Monthly container updates keep
the existing target selection and update command, write detailed logs locally,
and notify only changed images or failures.

`model/notification-policy.json` defines concise presentation for existing
model-generated reports. Apply explicitly as the Hermes runtime identity using
`hermes/apply_notification_policy.py --apply`; without the flag it previews.
Only prompts of named recurring jobs change, preserving IDs, delivery routes,
schedules, paused state, report facts and confirmation protocols. Prior prompts
are backed up in the private profile; rerunning is idempotent. Companion photos
already use a single sentence and keep their image delivery contract.

Run the notification regression checks with the existing Hermes Python runtime:
`PYTHONPATH=/home/hermes/.hermes/hermes-agent /home/hermes/.hermes/hermes-agent/venv/bin/python -m unittest discover -s checks`.

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
`email_transport=service-stdio` invokes the existing email application's native
MCP stdio transport in its container; account credentials stay in that service.
Both clients normalize MCP 1.x/2.x result fields.

Health and financial report consumers use Personal Records directly, configured
with `records_api_url` and `records_token_file` in the private Hermes config.
Install the `personal-records` base wheel in the consumer environment (no server
extra). Health freshness reads `/api/v1/sources`; reports request business date
summaries. Missing credentials or HTTP errors are explicit failures. Health
SQLite and bill JSONL/daily files have left the runtime chain.
`daily_health_summary.py --start-date YYYY-MM-DD --end-date YYYY-MM-DD`
returns inclusive-date API results. The read token stays outside this repository.
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

Favsync exception alerts accept the creator source's `cached` state when it
has no error. At the user's request, X `content_unavailable` assets are excluded
from attachment alerts; asset states and failed execution history are retained.
Execution history stays in Favsync rather than its notifications.
Rewards alerts name unsupported exploration topics;
the existing Rewards job runs at 09:30 and 16:30 (Asia/Taipei) from 2026-10-13,
retaining its job ID and delivery route. It verifies the preceding platform
cycle in the morning and handles the reset cycle in the afternoon. Receipts
include the platform task date and name unfinished daily streaks.
unconfirmed login and cart checks remain visible with their actual meaning.
Benefits exception reports show only each affected platform and its problem.
The verified GLaDOS, Yingshijufeng, Olé, Rainyun and WorkBuddy CN/international
jobs use this same path. Each attempt keeps its structured record at
`benefits-runtime/runs/<run_id>/result.json` and updates its independent delivery
receipt, including launcher failures and lock contention. Their no-agent jobs
use local delivery, so successful operations remain in execution history and
do not produce success notifications. Unknown business outcomes, including an
unconfirmed international WorkBuddy reward, remain visible in the exception
report. WeTalk and Yanxuan are not scheduled until credentials and current
interfaces are accepted.
Telegram bot check-ins run as `benefits-telegram-ai` (08:40) and
`benefits-telegram-nsfw` (08:43, Asia/Taipei) through the same launcher, with
deployment keys `telegram-ai` / `telegram-nsfw` and `platform: telegram`; the
shared browser lock serialises them. Some bots roll their day over after Taipei
midnight, so they run after 08:00. The exception report names each unconfirmed
bot; `bot_rejected` (captcha or join-channel gate) is shown as needing a manual
check-in. Opening Telegram Web is retried for about three minutes when the proxy
drops; commands are never resent.
Generation and result timestamps stay in the private receipts. Reports read the current delivery receipt on
each invocation; previously sent messages retain the snapshot from their send
time. Successful repair runs therefore remove the platform from the next
report, without rewriting its historical failure receipt.

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

## Face baseline

Scheduled scanning was removed at the user's request. The resident service only
scans on manual web/API requests. No face-baseline cron entry or wrapper is
installed; its former logs are retained. See `face-baseline/README.md`.

## Personal Review direct inputs

Business source is `personal-info/personal-review/`. CRM statistics use its
independent HTTP API; the daily agent reads conversations through current CRM
MCP tools. Records supplies health and bills. Skysight reads published per-device
manifests from its independent SFTP archive. The obsolete CRM snapshot, raw
retention and Hub exception schedules have been removed.

The NAS archive is private. `skysight-archive-read.sh` calls exactly
`sudo -n -u yuwk /usr/bin/python3 -I /home/yuwk/cron/hermes/skysight_archive_read.py`;
the sudoers rule permits only that command. The reader accepts a time window
and checkpoint, reads a fixed archive, and returns evidence over stdout without
writing a data copy. It does not accept paths or commands.

## Hermes 报告源码收束

独立 `hermes-cron-reports` 的报告统一在 [hermes/reports](hermes/reports/README.md) 维护。
已核对源文件并保留本仓库较新的修复；部署入口和现有调度不变。原仓库保留历史。
