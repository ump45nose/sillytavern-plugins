# NAS phase 5 execution — 2026-10-21

User authorized the fn portion of the attached phase-5 plan and creation of a private
`ump45nose/personal-review` repository for source publishing. Follow phase-5 §§2/6/7.

Scope: personal-review HTTP, Hub goals/review/stage proxy and attention, write methods,
App/Telegram first-confirmation coordination, CLI status and Lingjun Skill deployment.
Production validation is read-only or dry-run; real confirmation belongs to the owner.
Do not change generation, checkpoints, projections, job IDs/schedule/topic/history or
paused state. Do not touch Mac code or expand net/git coverage. Never print secrets.

Source worktree: `/vol1/1000/Code/.worktree/phase5-review-http-20261021`, branch
`codex/phase5-review-http-20261021`, base 895cd7e. Aggregate main has others' boot edits;
do not overwrite or merge into dirty main. Hub checkout: `/home/yuwk/src/personal-hub`.
Current Hub image before phase 5: local/hub-api:3d69313.

Decisions:
- Source uses stdlib HTTP server and the existing Hermes runtime; no shared runtime
  dependency upgrade. Bind LAN 18191 (verify availability before applying).
- Raw service bearer exists only in Hub private env. Source compares SHA-256 against
  a private hash file readable by hermes; no raw token in source env or service unit.
- Shared CLI/HTTP operation locking is required around service writes: existing
  idempotency checks do not serialize concurrent confirmations/external Memos writes.
  SQLite already uses WAL and the default five-second connection timeout.
- Cycle creation gains optional dry_run so every production write path can be checked
  without creating business data. New-goal retries deduplicate cycle_id/domain/goal;
  a changed payload for an unfinished identical goal is a conflict.
- Old weekly material has no material_json; HTTP derives display sections only from
  the existing frozen evidence, without regenerating or rewriting sessions.

Steps:
1. Source read endpoints and preview; tests, systemd deployment, production reads.
2. Hub goals/read/preview/status/attention; fake-source tests and targeted deployment.
3. Source and Hub write routes; shared locking/idempotency, production dry-run only.
4. App notification implementation, CLI status, Skill synchronization; preserve jobs.

Final acceptance: tests plus authenticated LAN/public goals and source read/dry-run.
Owner must perform an actual App confirmation; do not fabricate production sessions.

Progress: inspection complete; implementation starting. Current time 11:21 +08:00,
well outside tonight's 21:30 generation window. Existing timers/jobs remain untouched.
