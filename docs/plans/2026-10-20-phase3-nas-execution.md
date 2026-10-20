# NAS phase 3 execution

Scope and acceptance follow `2026-10-20-phase3-nas.md` §§2, 5, 9, 10.
NAS edits are limited to `services/hub-api/` and `docs/`; usage-monitor changes belong
to a separate aggregate worktree. Before every push, rebase on the remote main.

User clarified that retired local Hub artifacts should be deleted first. The aggregate
main already tracks no old Hub source. Removed its untracked environments, bytecode,
build packages and obsolete source links after checking current service mounts and
systemd/deployment references. Preserved Git worktrees, external backups and source data.
New checkout: `/home/yuwk/src/personal-hub`, outside the aggregate repository.

Progress (each step is tested and committed separately):

- Step 1: API skeleton, hashed device authentication, source isolation and bounded cache,
  safe errors, module envelopes, batch/status endpoints. Python 3.12 unit verification: 4 tests passed (authentication/revocation/hash, safe errors,
  cache/stale/24h expiry, concurrency/deduplication/timeout isolation).
  Live modules: none; LAN deployment is step 2.
- Step 2 code: read-only health/bills adapters, fake-source tests (6 tests pass),
  pinned Python Dockerfile and hardened Compose template. Deployed image `local/hub-api:4be5e1f` in independent `hub` stack.
  Live modules: health and bills; both real LAN module/status calls returned ok,
  each has 14 day rows. Actual wrong-port instance returned health=error/bills=ok.
  Host and Dockge Compose validation passed; browser card rendering not verified
  because this session has no browser controller. Runtime UID/GID, readonly root,
  cap drop and no-new-privileges verified.
  Boot source checkpoint: aggregate branch `codex/hub-api-sources-20261020`, `33c3d77`;
  deployed only the added hub-api line, preserving unrelated main edits.
  Boot check: missing=[], stopped_planned=[], active_unplanned=[ai-resource-center,
  oauth-disclosure] (outside this task). The main aggregate worktree remains dirty,
  so the source checkpoint is not integrated into main.
  Duplicati's existing selected-source backup now includes `/source/hub/data/`;
  existing schedule/destination/credentials retained, no backup run or restore test.
  Stack/runtime documentation updated. No source service restarted.
- Step 3 code: CRM/Plaud/Memos adapters, write forwarding, audio Range and transcript proxies; 8 tests pass. Deployed `local/hub-api:946a9af`; real LAN CRM/Plaud/Memos status=ok.
  CRM today=13 participant rows, Memos=20 rows at verification. Real existing
  audio Range returned 206/4096 bytes; transcript returned 200 text/markdown.
  POST forwarding tested against fake sources; no production records created.
  Existing source credentials reused; no source configuration or restart.
  Boot differences unchanged. Live modules: health, bills, crm/recordings, memos.
- Step 4: deployed `local/hub-api:07f0eef` and
  `local/usage-monitor-mcp:hub-http-ebd2389`. Existing usage Python source hashes
  matched the migrated aggregate source before editing. Offline release-wheel build
  and pip check passed; inherited old wheel merge fixed in the build source.
  Hub tests: 10 pass. Usage tests: 13 pass. Candidate full app health/HTTP auth and
  MCP initialize/tools discovery passed; production anonymous MCP init=401.
  Production HTTP net=200/24 hourly rows, limits=200/8 provider rows; source statuses
  token=ok/usage=ok. Token day/week/month/year=ok. Net=partial because subscription
  quotas/expiry are absent from the source; it returns actual observed traffic.
  Only usage and hub containers were recreated; all other IDs retained. Boot
  differences unchanged. OAuth/data/event state/old tokens retained.
  Source release pushed to app-configs branch `codex/hub-api-read-http-20261020`;
  boot line pushed to nas-cron-jobs branch `codex/hub-api-boot-20261020`.
  Aggregate main remains dirty and is not overwritten or merged.
- Steps 5–7: pending.

Pending user decisions are taken at the applicable step: GitHub token, missing source
credentials, and the Authelia restart window. Defaults for budget/health/cycle apply.
No Authelia or source service has been changed or restarted.
