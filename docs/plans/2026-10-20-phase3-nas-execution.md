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
- Step 3 code: CRM/Plaud/Memos adapters, write forwarding, audio Range and transcript proxies; 8 tests pass. Live deployment pending.
- Steps 4–7: pending.

Pending user decisions are taken at the applicable step: GitHub token, missing source
credentials, and the Authelia restart window. Defaults for budget/health/cycle apply.
No Authelia or source service has been changed or restarted.
