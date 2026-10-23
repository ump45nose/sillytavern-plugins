# Phase 5 personal-review HTTP — 2026-10-21

Scope/contract: personal-data-hub/docs/plans/2026-10-21-phase5-nas.md.
Development: aggregate worktree codex/phase5-review-http-20261021, base 895cd7e.
Source published with subtree split to user-approved private ump45nose/personal-review.
Deployment checkout /home/yuwk/src/personal-review; runtime links use that checkout.
Original config, DB, Memos credentials and artifacts remain in /vol2/1000/Docker/personal-review.
Aggregate main has others' boot edits and is not overwritten/merged.

Source read/preview and all requested write endpoints implemented. CLI/HTTP service
writes share a reentrant flock; existing idempotent receipts retain confirmed_from.
New-goal retry identity is cycle_id/domain/goal; changed payload conflicts. Dry-run
never creates indexes/Memos. The source stores only a private SHA-256 auth hash; raw
bearer remains in Hub private env. HTTP bodies/logs never expose credentials.

Step 1 source main af0a227: read endpoints, stage/comments, preview; 71 tests.
Step 3 source main 6f48ebe: writes and shared locking; 75 tests.
Step 4: readonly CLI status, only-first-App non-agent archive notification, source
Skill 1.1.0 and partial-close retry reuse; 80 source tests pass.

Native service template deploy/personal-review.service binds LAN 18191 as hermes.
Production stage/detail reads pass; 3 goals and one active cycle. LAN/public comments,
close and new-goal dry-runs=200, create-cycle dry-run=409 for existing active cycle.
Review/session/cycle/goal/idempotency/projection counts unchanged. Current source
CLI/generation/checkpoint/projection schedules and jobs are untouched.

Deployment Skill synchronization must compare the existing installed source before
replacement. Private rollback: Docker/backups/personal-review/phase5-20261021.
Owner must perform real App review confirmation; do not create test business data
or send a production test message. Final deployment evidence is recorded in the Hub
phase-5 execution plan.
