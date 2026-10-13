# Correctness batch (2026-10-02)

Base: `88eca04dda3baa6954991c2120a6d16df082e4cd`. No production state, sessions,
platform accounts, or media directories were accessed by the tests.

## Fixed paths

- **FS1:** XHS resumes a source/account-scoped unfinished walk. A checkpoint
  retains unread page entries, pagination progress and the original seen boundary.
  Queue entries, seen IDs, outcome and checkpoint commit together. The API does
  not promise snapshot-stable cursors: after any resumed walk, budgeted head
  verification retains the original boundary. Completion requires two consecutive
  traversals with the same ordered page-ID digest and no newly discovered IDs in
  the verification traversal. Deletion/reordering also changes the digest, even
  when no new IDs are found. This is explicit convergence evidence, not an atomic
  snapshot guarantee under continuous adversarial mutation. Old checkpoints
  without digests are revalidated conservatively without losing buffered entries.
  Existing numeric cursors, timestamps, baselines, frozen names and retry
  locators remain compatible; head inserts are processed during verification.
- **FS2:** Pixiv refuses every terminal gallery-dl `-1` event, including mixed
  successful records followed by auth, HTTP or unknown failures. At the pinned
  gallery-dl commit, such an event is emitted when DataJob dispatch aborts and
  still returns exit code zero. Deleted/My-Pixiv-only works instead produce
  warnings and ordinary metadata; those do not block a successfully exhausted
  baseline. Existing baselines are never reset.
- **FS4:** Asset and bundle failures use the same `ACCOUNT_ERRORS` set. A busy
  Telegram session stops that account's remaining work and notice collection;
  other configured accounts continue.
- **FS5:** Both existing and fresh single-file outputs must be regular, nonempty
  files. Invalid existing targets are preserved and remain failed. New output is
  atomically linked without replacement; a detected publication collision remains
  a collision on later retries until resolved. Valid legacy deterministic targets
  can still be accepted after a publish-before-DB crash, avoiding redownloads.
- **FS6:** Notice exports keep their dialog in each locator, but identify the
  session owner through a bounded empty Saved Messages export. The existing
  `tg_identity:<account>` subject key now guards both collections. Historical
  notice-dialog settings are left untouched; notice cursors and seen IDs are not
  reset. A notice-only account with no previously stored true subject establishes
  that identity on its first verified run; a pre-upgrade user change cannot be
  inferred retrospectively from the old bot-dialog ID alone.

FS3 (Bili concurrent names/publication) is tracked separately in the pinned
Bili build patch; no Bili database migration or production download runs occur
in this Python batch.

## Verification

Run `python -m unittest discover -s tests -v` in an environment with the base
dependencies. New regression modules are `test_correctness_20261002.py` and
`test_xhs_continuation.py`. They use temporary databases, files and subprocess/API
stubs. The original unmodified suite passed 37 tests before edits.

Tests cover baseline preservation, mixed errors, restart budgets, partial pages,
head insertions, transaction rollback, invalid output, concurrent target creation,
publication-before-DB failure, account isolation and notice-only identity changes.
No successful unit-test result claims live service or deployment verification.

## Rollout and rollback

Keep existing state/download/session mounts and account labels. Back up the
SQLite database and associated state directory together before a separately
authorized rollout. XHS checkpoints are additive settings, not a schema reset.
Do not run old/new workers together. Before rolling back to code that does not
understand continuation, let unfinished XHS walks reach `complete`; otherwise the
old worker can repeat the original missed-page defect. Preserve checkpoints in
the backup rather than deleting or converting production progress speculatively.
Any unexpected history requeue, identity mismatch or output conflict is a stop
condition, not permission to reset a baseline or overwrite a target.

Pinned upstream evidence: [gallery-dl DataJob](https://github.com/mikf/gallery-dl/blob/74a5aaf276df69f493ca8f68ebb478afe31a45ad/gallery_dl/job.py#L1109-L1145),
[Pixiv unavailable-work metadata](https://github.com/mikf/gallery-dl/blob/74a5aaf276df69f493ca8f68ebb478afe31a45ad/gallery_dl/extractor/pixiv.py#L155-L187),
[tdl 0.20.4 self export](https://github.com/iyear/tdl/blob/v0.20.4/app/chat/export.go#L78-L88).
