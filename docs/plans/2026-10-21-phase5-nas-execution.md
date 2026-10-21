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

Step 2 complete (11:52 +08:00):
- Hub image local/hub-api:562540e, 52 backend tests pass. goals TTL=60, review status,
  read/detail/preview proxies and three stable attention rules are live.
- Actual LAN/public: goals=ok with 3 goals; attention has one pending weekly review;
  daily/weekly details=200, blank open-weekly preview=422 with field key preserved;
  status=200 with 14 sources and review=ok. Temporary device removed. No business write.
- Source remains main af0a227. Only hub-api was recreated; source reads preserve
  raw bodies for the App and omit internal fields. No changes to net/git behavior.

Step 3 complete:
- Source main 6f48ebe (aggregate ac5efb5), 75 tests pass including cross-process
  first-confirmation locking, App audit source, goal publish-failure retry/no duplicate,
  dry-run nonmutation, all-goal outcomes and sixth-goal rejection.
- Hub image local/hub-api:1712dfb, 58 tests pass. All five write routes forward once,
  preserve validation/expired errors and invalidate goals after success or an uncertain
  write failure; dry-run keeps cache. POSTs are never automatically retried.
- Actual LAN/public comments, close and new-goal dry-runs each returned 200/dry-run.
  Create-cycle dry-run returned expected 409/conflict because the existing cycle is
  active. Review/session/cycle/goal/idempotency/projection counts are unchanged.
- No actual finalize, comments, close, new goal or new cycle executed in production.

Step 4 complete:
- Source code release fd6bd78; current private-repo main feabd88 adds standalone
  credential/cache ignore rules only. Aggregate code checkpoint 64c09c1, metadata df55f2c.
  The deployment checkout and source worktree are clean. Source repository privacy
  is verified. Source service is enabled/active as hermes, with NoNewPrivileges and
  readonly system paths except the original state/log directories.
- 80 source tests pass. Added only-first-App non-agent notifications, readonly review
  status CLI, exact source audit and Skill 1.1.0 synchronization. Dry-run/preview and
  duplicate confirms do not notify; notification errors cannot roll back an archive.
  Partial stage-close retries also reuse the original Memo and goal comments.
- Installed Skill matched its original source before replacement, and now exactly
  matches the release. All 11 personal-review job records (including runtime/history
  metadata) compare unchanged; all jobs retain IDs/schedule/topic/prompt/pause fields.
  Other jobs continued normally and only advanced their repeat.completed counters.
- The existing Hermes non-agent delivery directory is readable in a one-off service
  with the production service's User/NoNewPrivileges/readonly restrictions (exit 0).
  This was a read-only configuration check, not a Telegram send test.
- Final health/stage reads=200; mainline/cycle and 3 goals present, comments not degraded.
  Existing Hub credentials compare unchanged; only review URL/token were added, and
  the source's private hash matches. No configured Hub secret matches in Hub/source
  service logs. Only hub-api was recreated; Authelia, NPM and source containers retained.
  Hub image remains 1712dfb. Boot: missing=[], stopped_planned=[], original unplanned
  ai-resource-center/oauth-disclosure only.

Owner explicitly deferred real App archival acceptance on 2026-10-21. Code/deployment
and read/dry-run checks are complete; actual Memos archival and Telegram delivery are
NOT claimed as verified. Do not create production test business data or send a test
message to substitute for the deferred owner action. No manual confirmation remains
required to finish this code/deployment delivery.

Recovery/rollback: preserve live databases, OAuth/credentials, projections and cron
history. The phase5 private checkpoint contains the original source links, Skill, Hub
settings/tag/Compose and a pre-change SQLite backup. Restore only this release's code,
image, source links or specific config keys if needed; never overwrite current business
data with the pre-change DB merely to roll back code. Current deployment source is
/home/yuwk/src/personal-review; aggregate main still has others' boot edits and is not
merged or overwritten. Do not restart the shared login stack for this feature.

