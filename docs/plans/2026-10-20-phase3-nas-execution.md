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
  pinned Python Dockerfile and hardened Compose template. Deployment pending.
- Steps 3–7: pending.

Pending user decisions are taken at the applicable step: GitHub token, missing source
credentials, and the Authelia restart window. Defaults for budget/health/cycle apply.
No Authelia or source service has been changed or restarted.
