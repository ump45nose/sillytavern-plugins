# Hub v2 NAS execution — 2026-10-21

Scope: execute docs/plans/2026-10-21-hub-v2-tasks.md, network plans first, then
Plaud recording days, Token detail and own-user Memos CRUD. Layout remains opaque;
document Android preservation requirements. Only services/hub-api and docs in this
independent Hub repository are owned here; do not edit Mac code. Base 37c336b.

Boundaries: existing device bearer/OIDC, credentials, volumes and source identities
remain. No URL/header/body logging, no write retries, no production test business data.
Reuse source APIs; no durable mirror of source records. Fake services for write tests.
Original phase-5 real archive/Telegram acceptance remains deferred by owner choice.

Decisions/evidence:
- Usage HTTP has only current natural-month total and today's hourly counts. Manual
  reset_day=1 uses month_bytes; other reset days have unknown used_bytes. Shared router
  count is deliberately reused for each plan; no allocation/estimation.
- Token /api/stats historyPreview.daily is a 30-day tail (confirmed source and live
  shape). /api/history has full daily/perClient/perModel history (102 days at inspection).
  Preserve only allowlisted usage and title fields, never projects/account/content.
- Plaud existing archive detail reads Markdown. Owner clarification pending for a
  compatible metadata-only option/source restart to satisfy no-transcript-read listing.
- Memos list must bind current creator in official filter. Detail, patch, archive and
  attachment proxy must check ownership independently (admin token can see others).
  DELETE will PATCH state=ARCHIVED, never upstream DELETE.

Steps and acceptance:
1. Network plan storage, billing periods/pools and cache-based traffic attention;
   tests for limits, reset boundaries, unknown usage, invalidation and preferences.
2. Recording day pagination, overlap people match reused with CRM, metadata existence,
   max-four detail fanout and bounded 60s result cache; no transcript/audio body reads.
3. Full Token history and exact range attribution; null where source cannot establish
   an exact rolling interval, no extrapolation; top-20 sessions allowlist, USD cost.
4. Memos own-user pagination/filter/detail/create/update/archive and read-only attachment
   proxy; tests for ownership, filters, single forwarding, cache invalidation and errors.
5. Full Hub test suite, source-specific tests if changed, targeted Hub deployment and
   authenticated LAN/public read smoke. Preserve other container IDs/config/credentials.
   Record real coverage gaps and Android layout compatibility; commit/push checkpoints.

Progress: source/interface inspection underway. No business writes performed.

Network implementation complete: manual plan validation/storage, inclusive billing
periods and shared module/attention pool assembly. 36 focused tests pass including
network/configuration/attention and prior usage behavior. Deployment pending final
combined release. No production plan has been inserted.

Token implementation complete: full source history, exact rolling parts/device
history, top-20 today sessions with explicit allowlist. Five focused Token tests pass;
production read-only candidate reports history=102 days, day tools/models/devices/
sessions=4/9/4/20, week=6/24/4/null, month=11/49/4/null. Provider identities and arbitrary
rolling session detail are unavailable and remain null. No Token Monitor change.

Recording and Memos implementation complete; full Hub suite 89 passes. Source tests
23 passes. Owner approved metadata-only Plaud and shared Hub Range-streaming playback.
Source aggregate checkpoint a25bd5d, subtree/repository release 45d4e9a published;
HTTP service now selects /home/yuwk/src/plaud-archive/src through a single PYTHONPATH
entry in its existing private env, original venv/unit/workdir/identity retained.
No merge into dirty aggregate main. Plaud service active; candidate production list
reads return 2 days/4 recordings without text, Memos own list/detail/tag/search read
checks pass. Source write endpoints were not called.

Rollback checkpoint: /vol2/1000/Docker/hub/deployment-backups/v2-20261021, root0700,
private files0600. Saves original Hub tag/Compose, Plaud env/unit, container IDs and
Hub env hash. Rollback code via Hub image and removal of only the added Plaud source
selection key; retain current DB, audio, transcript, OAuth and job state.

Real LAN and public read acceptance passed on Hub cc45457:
- Plan GET=200, zero configured plans (no test plan added).
- All modules/status=200, 14 sources; only pre-existing net/git coverage is partial.
- Recording page=14 days/29 audio, next page=1 day. Metadata presence booleans valid.
- MP3 and Ogg Opus each return 206 for bytes 0–31 and 4096–4127 on LAN and public;
  Content-Range/Accept-Ranges/private-no-store verified; anonymous audio=401.
  Whole-day Markdown=200 on demand. Existing inventory=15 days/33 audio (29 MP3,
  4 Opus). This is real HTTP seeking verification; native client decode/playback
  has not been exercised by this NAS run.
- Memos own list/detail and official tag/content filters=200; pagination token present.
  Actual create/patch/archive/attachment images were not exercised on production;
  fake-source tests cover these paths without creating business records.
- Token complete history=102 days for every range; day/week/month models=9/24/49,
  today sessions=20, arbitrary rolling sessions=null as documented.
- Temporary acceptance device revoked; both LAN/public return401 afterward.
- Only Hub container ID changed. Hub credentials/Compose definition and Plaud unit
  compare unchanged; Plaud env differs only by approved source-selection PYTHONPATH.
  Hub healthy as1000:1001, readonly root, ALL caps dropped, no-new-privileges.
  No configured secrets or request access URLs found in Hub/Plaud logs.
- Formal Compose validates on host and inside Dockge. Boot missing/stopped=[];
  ai-resource-center, ai-resource-center-server and oauth-disclosure were already
  unplanned before this change, confirmed in the saved container baseline.

Final review also makes manual expiry independent of router cache availability;
regression covers offline expiry and dismiss with no source I/O. Final image pending.
