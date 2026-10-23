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
- Step 3 code: CRM/Plaud/Memos adapters, write forwarding, audio Range and transcript proxies; 8 tests pass. Deployed `local/hub-api:946a9af`; real LAN CRM/Plaud/Memos status=ok.
  CRM today=13 participant rows, Memos=20 rows at verification. Real existing
  audio Range returned 206/4096 bytes; transcript returned 200 text/markdown.
  POST forwarding tested against fake sources; no production records created.
  Existing source credentials reused; no source configuration or restart.
  Boot differences unchanged. Live modules: health, bills, crm/recordings, memos.
- Step 4: deployed `local/hub-api:07f0eef` and
  `local/usage-monitor-mcp:hub-http-ebd2389`. Existing usage Python source hashes
  matched the migrated aggregate source before editing. Offline release-wheel build
  and pip check passed; inherited old wheel merge fixed in the build source.
  Hub tests: 10 pass. Usage tests: 13 pass. Candidate full app health/HTTP auth and
  MCP initialize/tools discovery passed; production anonymous MCP init=401.
  Production HTTP net=200/24 hourly rows, limits=200/8 provider rows; source statuses
  token=ok/usage=ok. Token day/week/month/year=ok. Net=partial because subscription
  quotas/expiry are absent from the source; it returns actual observed traffic.
  Only usage and hub containers were recreated; all other IDs retained. Boot
  differences unchanged. OAuth/data/event state/old tokens retained.
  Source release pushed to app-configs branch `codex/hub-api-read-http-20261020`;
  boot line pushed to nas-cron-jobs branch `codex/hub-api-boot-20261020`.
  Aggregate main remains dirty and is not overwritten or merged.
- Step 5 media: deployed `local/hub-api:46d53dd`; 12 hub tests pass.
  All four media sources=ok, rows resume/latest/albums/downloads=8/8/6/6.
  Real authenticated signed cover proxy=200. Only hub-api additionally joined
  existing media_net for the actual MoviePilot API at moviepilot:3001. All source
  containers/configurations were retained. MoviePilot LAN 28900 was actually the
  separate Emby STRM API; corrected the observations in the plan.
  qbit_manage's existing user/pass are empty; a bounded read from the hub container
  already returns 200, so the same trusted-network access is explicitly retained.
  Its authentication policy was not modified. Source cookie isolation and signed
  reference tampering/expiry are covered by tests.
- Step 5 GitHub: user authorized existing NAS gh classic/OAuth credential reuse for read-only API. Deployed local/hub-api:2b48ca1; 14 fake-source tests pass. Live GitHub source=ok, git=partial (bounded coverage), waiting=13, blocked=23. Actual fetch 7.5s; only GitHub uses configurable 15s, all other sources retain 5s. Media remains ok.
- Step 6 code: atomic layout/preferences, CNY subscriptions with bounded charge matching, seven cache-only attention rules and shared Git handling. 19 tests pass, including concurrent CAS and config/read races. Deployed local/hub-api:d12898e. LAN all-module/status=200; subs/attention=ok (0/7 rows), preferences=200/version0, absent layout=404. No production configuration/test records were inserted.
- Step 7 activated after the owner explicitly confirmed an immediate Authelia restart
  on 2026-10-21. Added only personal-hub to the existing seven OIDC clients; all other
  Authelia configuration, identities, secrets and source credentials compare unchanged.
  Removed HUB_DEV_TOKEN and activated production OIDC with exact verified sub allowlist.
  Step-7 activation image 4c7d8a7; the default and configured public URL both use 28443.
  NPM created only proxy host 42, certificate 2, LAN 18190, no forward-auth, access logs
  disabled and request error logs suppressed. Other NPM hosts compare unchanged.
  Public base is **https://hub-home.172906573.xyz:28443**. Actual public 443 does not
  reach the NAS certificate, while 28443 is the established direct NPM entry. Updated
  the shared interface before changing only this client's callback/public URL; no
  router, DNS, Tunnel or other public route was changed. Authelia is healthy.
  Actual public auth/start=302, secure binding cookie/no-store present, registered
  provider authorization=302 to the login portal. This is not a completed login.
  LAN and TLS-verified public-domain modules/status each returned 200 using a temporary
  internally issued device credential; all 13 sources returned status, and that device
  was revoked through the API (next request=401). Eight modules ok; net/git partial for
  the previously documented source coverage. No source business records were written.
  A runtime log scan found none of the configured secrets. Existing source container
  IDs retained; only hub-api was recreated. Other tasks may create their own temporary
  containers and are not modified by this work.
  Real human browser acceptance completed on 2026-10-21 at 10:16 +08:00 on the
  owner's MacBook Pro, through Desktop Commander after the device came online.
  scripts/device-login-smoke.py opened Chrome; the owner completed Authelia login,
  two-factor authentication and personal-hub consent. The browser returned to the
  random 127.0.0.1 loopback listener; actual PKCE token exchange succeeded.
  Public modules/status both returned 200, with 13 source entries. The temporary
  device was revoked through the API; the next authenticated request returned 401.
  Helper exit code 0 and success=true. Tokens stayed in memory; output contained only
  statuses/counts, and no source business records were written. 31 backend tests pass.
  NAS phase-3 API acceptance is complete; Mac application integration is separate.

Recovery: read this execution record, the phase-3 plan and requirements first.
Checkout main `/home/yuwk/src/personal-hub`; `git pull --rebase` before the next push.
Production image is 3d69313 (attention copy fix; later documentation commits do not change code).
Actual private env is stacks/hub/env/hub.env, 0600; never display its values.
Aggregate source worktree is `/vol1/1000/Code/.worktree/hub-api-sources-20261020`.
It is clean, with source changes committed and subtree release branches pushed;
main has unrelated boot edits. Do not merge/overwrite that dirty main.
Private deployment rollback files are `/vol2/1000/Docker/hub/deployment-backups/`;
restore only this task's changed fields and preserve live business/OAuth data.
Boot check at 2026-10-21 10:13 +08:00 has only ai-resource-center/oauth-disclosure
unplanned, no missing or stopped planned containers. Another task's earlier temporary
favsync-eh-verify-20261021 container is no longer present. Dockge browser cards remain
unverified; both Compose contexts were validated. Duplicati backup/restore and production source writes were
not triggered merely for testing.

Authelia restart was explicitly approved and applied. GitHub reuse was approved; source credentials were available. Defaults for budget/health/cycle apply. Real browser/loopback/token/revocation acceptance passed at 10:16 +08:00. Usage-monitor was the sole source restart (step 4); Authelia was restarted for the new client in step 7.

Final deployment checks (2026-10-21): hub-api 4c7d8a7 healthy, UID/GID 1000:1001,
readonly root, cap_drop ALL and no-new-privileges retained. Public health=200; the
removed development token=401. Nginx configuration test passed, wildcard certificate
2 remains unchanged. Source credentials and seven previous Authelia clients compare
unchanged; only the new personal-hub callback uses public 28443. No business writes.
Both the earlier NAS test device and the real browser acceptance device were revoked.
Real browser acceptance used an actual OIDC login, not an internally issued credential.

Real desktop acceptance (2026-10-21 10:16 +08:00):

| Module | Status | Row counts |
| --- | --- | --- |
| health | ok | days=14 |
| bills | ok | today_items=0, days=14, month_categories=1 |
| crm | ok | today=2, stale=5 |
| media | ok | continue_watching=8, latest=8, recent_albums=6, downloads=6, services=4 |
| token | ok | tools=3, devices=4, limits=8 |
| net | partial | hourly=24; upstream quota/expiry facts absent |
| git | partial | waiting=18, blocked=22; bounded source coverage |
| memos | ok | recent=20, tags=14 |
| subs | ok | items=0 |
| attention | ok | items=9 |

No runtime configuration, source credential or image change was needed for this
acceptance. Browser acceptance used local/hub-api:4c7d8a7. Aggregate source integration
into main remains deferred because the main worktree has others' uncommitted boot
changes; the isolated source checkpoints and subtree release branches are pushed.

Attention copy correction (2026-10-21 10:40 +08:00, deployed):

- Scope: readable provider names without duplicated window prefixes; readable reset,
  renewal and expiry subtitles in Asia/Shanghai. Preserve machine timestamps, IDs,
  deduplication/dismiss/snooze state and existing net/git source behavior.
- Subscription configuration remains untouched; an empty list is valid.
- Acceptance: reproduce the original title/ISO subtitle problem in regression tests,
  cover local-day/year boundaries and missing time, then run backend tests and verify
  the deployed authenticated token/attention API. Update only hub-api through the formal
  hub stack, preserve credentials/data and record the released image/checks here.
- Code verification: regression tests reproduced the duplicate lowercase Cursor title
  and raw date subtitles before the change. All 45 backend tests now pass, including
  title boundaries, same-day/tomorrow/later/year-boundary reset times, missing/invalid
  timestamps, unchanged source timestamps/IDs and dismissal through the existing ID.

- Release: local/hub-api:3d69313 is healthy. Before deployment, the actual API showed
  one duplicated lowercase Cursor title and three raw ISO reset subtitles. Afterward,
  both LAN and TLS-verified public token/attention/subs requests returned 200; all three
  token reminders have readable titles/reset subtitles, including
  `Cursor Models 额度已用 100%`. Existing reminder IDs match the pre-release IDs,
  while token window reset fields remain timezone-aware ISO timestamps.
- The temporary verification device was revoked; the next public request returned 401.
  Only hub-api was recreated. The private credential file and subscription document
  hashes are unchanged, with zero configured subscriptions. No source business writes
  or source/Authelia/NPM restarts. Container hardening remains 1000:1001, readonly root,
  cap_drop ALL and no-new-privileges. Boot check: missing=[], stopped_planned=[],
  existing unplanned=[ai-resource-center, oauth-disclosure].
- Private rollback checkpoint:
  `/vol2/1000/Docker/hub/deployment-backups/attention-copy-20261021`.
  Restore only this release's image tag if needed; preserve live data and credentials.
