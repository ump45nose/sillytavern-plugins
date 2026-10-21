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

Step 1 complete (11:45 +08:00):
- Private source repository created and published: ump45nose/personal-review, main
  af0a227 (aggregate checkpoint 454361d). Deployment checkout /home/yuwk/src/personal-review.
- Runtime static source links now point to that checkout; all config, databases,
  credentials and artifacts remain at the original runtime directory. Private rollback
  checkpoint /vol2/1000/Docker/backups/personal-review/phase5-20261021 includes original
  links, a SQLite backup and Hub env before the two added review settings.
- personal-review.service enabled/active as hermes:hermes, LAN 18191 only. No source
  container, Authelia or NPM restart. CLI executable mode is preserved in Git releases.
- Source tests: 71 pass. Existing script forwarding import behavior and obsolete
  finance fixture were corrected for the suite; cron execution/business rules retained.
- Found and fixed existing weekly empty-template validation: template guidance must
  not count as a user conclusion. Production blank weekly preview=422, no write.
- Production: anonymous stage=401; authenticated stage=200, mainline/cycle present,
  3 goals, close=none, no comments degradation. Latest daily finalized/detail=200,
  material sections=8, delivered present; latest weekly open/detail=200, legacy frozen
  material readable, delivered=null. No production sessions or Memos created.

Step 2: Hub goals/read/preview/status/attention implemented; fake-source tests running.
Existing timers/jobs remain untouched; deployment is well before 21:30.

