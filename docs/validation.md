# Validation of the local media maintenance candidate

Date: 2026-10-02. All task actions were in the cloud workspace, using temporary files, stubbed services and local test databases. No user device, NAS, real download account or production service was exercised.

## Fixed-source checks

- FilmWatchlist source: `446ec9f81490a3555feefd8742e9ec9933feba1b`, based on `931a2897f1c77d53c6d9a6ca63202965547c4cac`
- Theme source: `c3155718ba01a2493394308345b424abf2c431cb`, based on `2064e165c7e307696d4e39d033799a649c3ac599`
- Optional download package: Favsync `d9f3ea93ed4f0e6f2fe96f8d05e38b57bd8d2a8e`, `packages/downloads`, version `0.1.0`
- The Film regression subset failed 11 cases on the untouched baseline and passed 4. The final Film suite passes all 49, including the 7 original smoke scripts
- The final Theme suite passes all 141 with the optional package absent and again with its installed wheel
- An independent reviewer separately verified Film's 49 cases and the publisher-stage Theme's 121 cases before final transport/layout checks

## Layout/build checks

- The relocated tree passes `tools/check_layout.py`, Film 49/49 and Theme 141/141 through `tools/test_all.sh`
- A copy containing only the Film plugin directory plus offline tests passes 49/49, showing it does not import another repository-root package
- `npm ci` and `npm run build` succeed from `frontends/theme-studio`. Building again through the legacy application-local frontend link produces the exact same distribution file hashes, in root `plugins.v2/themestudio/dist`
- Vite's output path is anchored to `import.meta.url`, so it is independent of the caller's working directory
- The relocated Theme project builds an independent wheel. Installing it into an isolated target, loading the CLI/publisher/media-budget modules, and running CLI help/version succeeds
- Theme wheel SHA256: `b6524f4dbb2d05845e14576a962e1333c59ef1568a9869b8fcdcc862b59c1080`
- Shared-download wheel SHA256: `b6ba27b88ade61403059741fac52d681d5682f9b00455ee25bddbc8427a82c25`
- Python compilation, dependency checks and whitespace/diff checks pass
- MoviePilot class names, config prefixes, manifest versions, root plugin paths and Theme's Unix socket path are preserved. Worker and plugin dependencies remain independent

## Covered behaviors

Film checks include PT/share successful receipts; pre-submit persistence failure; accepted submission followed by a local write failure; unknown outcomes without candidate retry; saved-task recovery with disabled M-Team, missing source or source outage; legacy handles and season metadata; frozen cloud targets; writable source identity/alias checks; completed-source reset/correction; stale library-fact clearing; Chinese/English/enum media types; one-way new candidate IDs and compatible old IDs; and shared torrent parsing without preview/playability conflation.

Theme checks include NULL-provider adoption; bounded delayed Emby hash refresh and paced HTTP failures; consistent large full-track budgets; typed search and selected-download failures; a single configured search orchestrator; preview/lock/ownership conflicts; durable replacement intent; DB failure and interruption; hash-guarded rollback; stale replacement-journal rereads under the item lock; early streaming-client disconnect; and optional shared transport present/absent behavior.

## Remaining limits and decisions

- No Docker executable was available, so the base image and optional wheel-overlay image were not built. The independent build context and its inputs were inspected; container operation is unverified
- The current Favsync film API has no conditional revision/CAS write. A fresh identity check precedes PATCH, but a concurrent source edit between those calls remains possible. No API or physical database migration was introduced
- Automatic first-file Theme publication retains its pre-existing window between filesystem publication and ownership DB persistence. A crash there can leave an unindexed external file. Do not equate replacement/manual-apply journal tests with complete first-write atomicity
- The optional shared package is locally built and tested. Its standalone fallback remains intentionally available; transport duplication is therefore reduced by an opt-in integration boundary, not fully removed
- Production MoviePilot/P115/Emby compatibility, real media/network behavior and deployment remain unverified. There was no remote push, repository creation/rename/archive, merge, release, production state migration or deployment
- Theme's license and third-party notices retain their original scope. No blanket license was added to the combined tree
