# Hermes recurring schedule restoration

On 2026-10-06, all 25 paused recurring jobs were resumed through the Hermes
job-management API. The scheduler now has 48 enabled recurring jobs and no
paused recurring jobs. Resume calculates future occurrences; completed or
expired one-shot records were preserved without replay.

Changes deployed under `/home/yuwk/cron`:

- Email collectors reuse the existing Data Hub local read-only bridge. Account
  secrets and OAuth identities remain with the existing service. MCP 1.x/2.x
  response fields are normalized, and incomplete collection returns failure.
- Health freshness, daily summaries and Personal Review consume the current
  Data Hub reader API. Window queries paginate with an explicit budget; an API
  failure never falls back to the retired SQLite snapshot.
- HA and NPM probes use actual listener URLs from private configuration.
- The six legacy container schedules were renamed to reflect the persistent
  deployment policy. Former stop/enforcement windows audit the boot plan;
  former start windows repair startup. Only existing planned containers can be
  started. Unlisted containers are left alone, and model services stay running.
- Both runtime identities can acquire the boot lock without truncating a
  differently owned file in `/tmp`.
- Missing daily/weekly review skills were rebound to `personal-review`, using
  bounded preparation prompts in `model/review-prompts.json`.
- PLAUD uses its existing migrated `model/plaud-daily.sh` entrypoint.

Existing feature flags still control stage and external projection business
operations. Enabling their schedules does not enable disabled application
features. The two daily draft schedules and two weekly draft schedules remain
separate, as requested when restoring all recurring jobs.

Validation used syntax/import checks and single-path business probes only:
CPA HTTP 200; email collection succeeded with zero account errors; current
health data and review health evidence were read successfully; persistent
container audit, startup reconciliation, HA probing and both boot-lock runtime
identities passed; PLAUD doctor reported ready. Full PLAUD processing and all
model review jobs were not manually triggered. Runtime job records, private
routing, tokens, collected content, outputs and backups are excluded from Git.
