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
