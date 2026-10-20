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
- Step 5 media: deployed `local/hub-api:46d53dd`; 12 hub tests pass.
  All four media sources=ok, rows resume/latest/albums/downloads=8/8/6/6.
  Real authenticated signed cover proxy=200. Only hub-api additionally joined
  existing media_net for the actual MoviePilot API at moviepilot:3001. All source
  containers/configurations were retained. MoviePilot LAN 28900 was actually the
  separate Emby STRM API; corrected the observations in the plan.
  qbit_manage's existing user/pass are empty; a bounded read from the hub container
  already returns 200, so the same trusted-network access is explicitly retained.
  Its authentication policy was not modified. Source cookie isolation and signed
  reference tampering/expiry are covered by tests.
- Step 5 GitHub: user authorized existing NAS gh classic/OAuth credential reuse for read-only API. Adapter and 14 fake-source tests pass; production verification pending.
- Steps 6–7: not started, following §10 order. Authelia/NPM unchanged; no public
  endpoint or OIDC login acceptance claimed. Local LAN dev credential remains active.

Recovery: read this execution record, the phase-3 plan and requirements first.
Checkout main `/home/yuwk/src/personal-hub`; `git pull --rebase` before the next push.
Production image is 46d53dd (later documentation commits do not change code).
Actual private env is stacks/hub/env/hub.env, 0600; never display its values.
Aggregate source worktree is `/vol1/1000/Code/.worktree/hub-api-sources-20261020`.
It is clean, with source changes committed and subtree release branches pushed;
main has unrelated boot edits. Do not merge/overwrite that dirty main.
Private deployment rollback files are `/vol2/1000/Docker/hub/deployment-backups/`;
restore only this task's changed fields and preserve live business/OAuth data.
Boot check still has only ai-resource-center/oauth-disclosure unplanned, no missing
or stopped planned containers. Dockge browser cards remain unverified; both Compose
contexts were validated. Duplicati backup/restore and production source writes were
not triggered merely for testing.

Pending user decisions are taken at the applicable step: GitHub token, missing source
credentials, and the Authelia restart window. Defaults for budget/health/cycle apply.
No Authelia or source service has been changed or restarted.
