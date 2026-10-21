# hub-api

Python 3.12 thin backend. Source business records remain in their owning applications.
Only devices, preferences/layout, subscriptions, manual network plans and attention handling are durable;
normalized source responses are cached in memory for their TTL and for at most 24 hours on failure.

```sh
uv sync --locked
uv run pytest
HUB_DATABASE=/tmp/hub.sqlite uv run uvicorn hub_api.app:create_app --factory --host 127.0.0.1 --port 8080 --no-access-log
```

Configure `HUB_DEV_TOKEN` only for LAN integration; omit it in production.
All `/api/v1/*` routes require a Bearer device or development token. Status is read-only
and never triggers source requests. Source failures expose only a type and HTTP status.
The application and server must not log request URLs, headers, bodies or source responses.

## Health and bills

Live adapters use the existing read credential. Health pulls exactly 14 local calendar
days (at most four requests in flight); the source list API does not expose per-day
sleep/heart-rate measurements. Absent days and absent measurements remain null.
Sleep duration follows the source's interval-union rule, subtracting awake intervals;
`light` maps to `core`. Resting heart rate/SpO2 use the latest sample of the day.

Bills use confirmed `expense` records in CNY. Income, transfers, refunds, pending
records and other source business types are excluded; currencies are not converted.
Source summaries calculate totals/categories, and today's details are paginated.
A successful exhaustive summary establishes a zero-spend day; missing measurements
are never filled with zero. The source has no assets API, so asset fields remain null.

`records_health` and `records_bills` have separate 60-second caches and status entries,
so one API failure does not remove the other module. Sources with missing credentials
explicitly report `unconfigured`.

## NAS

Formal entry: `/vol2/1000/Docker/stacks/hub/compose.yaml`. Build this directory's
Dockerfile, use a source commit tag, set `HUB_IMAGE_TAG` in the stack `.env`, and copy
`deploy/compose.yaml` to that entry. Actual credentials belong only in `env/hub.env`.
The container writes only `/data` and bounded `/tmp`, and exposes LAN port 18190.
The bind directory `/vol2/1000/Docker/hub/data` is the `hub-data` store; it is registered as `/source/hub/data/` in
Duplicati's existing selected-source backup (schedule and credentials retained). Source containers are accessed through existing
LAN listeners and require no configuration changes.

Run verification from **this directory**: `uv run pytest`.


## CRM, recordings and Memos

CRM pages people and the current 42-day interaction window using cursor pagination.
Only minimal contact fields, today's interaction previews and cycle counts enter the
short-lived cache. A multi-person interaction appears once per participant in `today`;
cycle interaction counts remain distinct. Never-contacted people have unknown elapsed
days and are omitted from the stale-contact list.

Recordings prefer existing available CRM audio attachments. Otherwise match Plaud
recordings on the same local date by overlapping time intervals; point interactions
must fall inside the recording. Prefer greatest overlap, then nearest start, then ID.
Missing start/duration or no match yields null. Recording IDs encode only source,
date and source ID. The proxy accepts those fixed ID formats, streams audio with Range
and serves the whole day's Plaud Markdown transcript. CRM attachments have no transcript
API, so their transcript request returns 404. No arbitrary URL is accepted.

Live Plaud uses its existing LAN listener on **18095**, verified read-only; the plan's
older 127.0.0.1:8092 observation did not describe the actual service. No source listener,
container or network was changed. Memos uses its existing token, `/auth/me`, the latest
20 own NORMAL memos and official per-user tag statistics; it never scans all memo bodies.
Both write endpoints forward once without retries. `person_name` must uniquely match
an existing CRM contact; ambiguous/unknown names return 409, and no contact is invented.
Unit tests exercise writes with fake services; no test memo or interaction is inserted
into production merely for validation.

## Token and network data coverage

Token Monitor `/api/stats`, `/api/history` and `/api/devices` are read concurrently,
once per 30-second source refresh, shared by all selected ranges. `historyPreview`
is a 30-day preview; the full authenticated history endpoint provides all recorded
days (102 days at deployment inspection). Daily/per-client/per-model and per-device
history are allowlisted before caching. Only session titles and usage are retained;
no conversation content, project paths, accounts or credentials. Source services are
unchanged. Cost stays the source's estimated **USD**, with no currency conversion.

| Field | Coverage |
| --- | --- |
| history | all source-recorded daily totals/costs, independent of selected range |
| tools/models | exact selected rolling interval, live today plus dated historical attribution; descending total |
| devices | same interval; each device has null total/cost if any required date is absent |
| model provider | null: aggregate model attribution contains no provider identity |
| sessions | today's top 20; a rolling interval uses source calendar-month sessions only when boundaries exactly coincide and details are complete |
| sessions for ordinary week/30-day range | null: no dated session history; calendar-month cumulative usage cannot establish rolling usage |
| session model/device/title | null when multi-model, device attribution ambiguous, or title not synchronized |
| hourly buckets | null cells: source has no hourly token history |
| month buckets | unchanged (null); the new UI reads full history and selected-interval parts |

Unknown historical days leave interval totals/cost/attribution unknown; never zero-fill
or estimate. Year keeps the existing Monday-aligned 371-cell grid, with absent/future
cells null. History is only an in-memory source cache; Hub creates no durable archive.

Usage Monitor GET `/api/v1/net` reads existing ShellCrash SQLite through a read-only
transaction and grouped SQL queries. Missing/future hours remain null. Observed bytes
may omit collection gaps, so net remains partial. Provider quotas/expiry are entered
in Hub's manual plans below; route classes are never treated as subscription usage.

## Media

Each of the four media services is isolated with its own 30-second source cache.
Emby uses the existing theme-worker API key and the unique account matching the NAS
owner `yuwk`. Navidrome credentials come from the existing taglab worker; Subsonic
read operations use POST form parameters so credentials cannot enter URL/access logs.
MoviePilot uses header `X-API-KEY` with its existing integration key; qBittorrent
reuses the current qbit_manage connection configuration. When that configuration
explicitly has empty credentials, use its existing trusted-network read access; never
change the source authentication policy. Configured credentials use a separate SID
cookie jar and one login refresh on 403. Stateless source requests discard cookies so credentials cannot cross sources
sharing the same LAN address and different ports.

MoviePilot's actual API is `http://moviepilot:3001`, reached by adding **only hub-api**
to the existing `media_net`. No media service is reconfigured. LAN 28300 is its website;
28900 is the separate Emby STRM endpoint, rather than the MoviePilot API. Other
media APIs use their existing LAN listeners. Service links use existing NPM domains
on 28443; qBittorrent retains its existing LAN WebUI because it has no NPM entry.

Resume/latest/albums/downloads are bounded at 8/8/6/6. MoviePilot is probed through
its authenticated download API; qBittorrent supplies active incomplete download rows
without duplicating them. An unavailable service leaves only its own fields null.
Image references contain a source/item ID and 24-hour expiry signed by a dedicated
server key. Authenticated proxies accept only these references and fixed source
routes, never arbitrary URLs, and expose no upstream key or cookie to clients.

## GitHub

The owner authorized reuse of NAS gh's existing classic/OAuth credential, including
notifications/repo read access. The adapter sends only REST GET and fixed GraphQL
`query` operations; dismiss/snooze never writes notifications, issues or PRs.
Unread participating notifications map mention/team mention, review request and
comment/author reasons to waiting rows. Closed items and conversations last answered
by the owner are excluded. Review requests must remain outstanding. Fine-grained
credentials use the documented Search approximation, not notifications.

Reads run concurrently. The measured GitHub API needs about 9.5 seconds for the
notification-detail pipeline; GitHub alone uses a configurable 15-second deadline
(`HUB_GITHUB_TIMEOUT_SECONDS`). Other sources retain the five-second default. Notifications are
bounded to 50, own open PRs to 20, latest reviews/check contexts to 20. Activity totals
come from contribution collections; commit streaks use up to 40 newest commit days
per repository across 25 repositories and 365 days. Unknown coverage produces null
streak and partial status, rather than an invented count. Paginated notification/PR
results also produce partial. CI failure, changes requested, conflicts and no review
are separate blocked conditions. Unknown onset remains null until local observation
in the attention layer; it is never inferred from an unrelated PR update.

## Configuration and attention

Layout and preferences use atomic SQLite compare-and-swap with `If-Match`; the first
version is zero. A conflict returns `current` in the error envelope. Layout documents
remain opaque JSON objects, limited to 64 KiB; request streaming also has a bound.
Preferences GET returns default values with version zero until first saved. PUT uses
`{document: {...}}`, fills omitted preference fields with defaults and rejects unknown
fields. Goals/budget are applied after cache reads. Cycle start selects one 42-day
window; today's interactions/recordings are still read when outside that window.
Changing cycle/config waits for affected in-flight reads before discarding their cache.

Subscriptions replace `{items: [...]}`, at most 100 unique IDs. Amounts are CNY with
cent precision; no currency conversion is implied. Annual prices divide by twelve,
rounded to cents; monthly total sums the displayed equivalents. Last charge uses
case-insensitive subscription-name substring matching in confirmed CNY expense item,
merchant or note. One newest-first paginated stream covers the last 400 days, stops
once every item matches and retains only matching date/amount. It is bounded to 10,000
rows and the usual source deadline; truncation or unavailable source marks subs
partial, while local subscription configuration remains available. Unmatched charges
are null. Empty subscription configuration never queries bill history.

Attention evaluates all seven NAS rules exclusively from available source caches and
local configuration. Source data older than 24 hours is excluded. `source_down` uses
collector `observed_at` when available, otherwise the last successful read; it reports
continuous failure after 30 minutes or data age over six hours. Status/attention calls
never refresh sources in the background. A client batch refreshes requested modules
before attention is calculated. No notifications or background polling is added here.

Attention titles use provider display names and omit a repeated provider prefix in
window labels: `Cursor Models 额度已用 100%`. Subtitles are display text: reset times
use Asia/Shanghai (`20:00 重置`, `明天 00:30 重置`), later dates include month/day and
cross-year dates include the year. Renewal/expiry subtitles include the event label.
Absent reset times remain null. Source timestamps, attention IDs and handling state
retain their original formats and meanings.

Handling state stores IDs, first onset, dismissed flag and snooze deadline only. Known
GitHub onset is preserved; unknown conflict onset begins at local observation. All
GitHub conditions are observed even before the age threshold so a card can be handled
immediately. Both GitHub rows and attention rows respect the same state. An observed
end removes handling state, allowing a new episode to notify again; incomplete or
failed source reads do not establish that an absent condition has ended. Token windows
with a known reset time get distinct IDs for the new quota period.

## Device login and production activation

Configure issuer, confidential client secret, public URL and `HUB_ALLOWED_SUBJECTS`
(exact verified Authelia `sub` strings). Production startup rejects coexistence with
`HUB_DEV_TOKEN`. Redirects are restricted to the documented loopback path with an
explicit valid port, or `personalhub://auth`. Browser login has random provider state,
nonce, a Secure/HttpOnly/SameSite=Lax browser-binding cookie, and a separate
server-to-provider S256 verifier. Pending state expires in ten minutes. The returned
client exchange code expires in 60 seconds and is consumed atomically with device
creation; even a wrong verifier consumes it. Database identifiers/codes/device tokens
are hashed. Provider access/ID tokens are validated in memory and never stored.

ID tokens require RS256 signature, issuer, audience, timestamps, nonce and an allowed
subject. Discovery/JWKS cache for five minutes and must remain on the configured HTTPS
issuer hostname; Authelia advertises issuer on 443 and protocol endpoints on
28443, so the metadata may select a different HTTPS port on that same host.
An unknown signing key triggers one refresh. All `/auth/*` responses
are no-store/no-referrer; requests are limited to 30 per minute per observed peer,
with at most 1,024 rate counters and 1,000 unexpired login records. Forwarded client
addresses are not implicitly trusted. The private single-owner deployment can share
the NPM peer counter. Devices can be revoked immediately through the existing API.

Authelia and NPM example files are templates, not automatic deployment scripts. The
NAS candidate is privately prepared outside Git and validated with the running
Authelia image against read-only configuration/secret mounts. Applying it requires
the owner-confirmed restart window. Recheck the original configuration hash before
merging; preserve external changes. NPM uses existing wildcard certificate 2, LAN
port 18190 and public HTTPS port 28443, with no forward-auth. Public 443 does not
reach the NAS certificate; existing direct NPM applications use the same 28443 port. Disable access logging and request error logging for
this host because authorization callbacks contain one-time credentials.

At activation, merge only OIDC keys into the current private hub env and remove the
development token, register only the new `personal-hub` Authelia client, and restart
Authelia in the confirmed window. Then update only hub-api and create the single new
NPM host. Verify browser login/loopback/token/revocation and authenticated LAN/public
module and status requests; fake-provider tests do not establish real browser acceptance.


For the final interactive browser check, run `python3 scripts/device-login-smoke.py`
on a computer with a desktop browser. It opens Authelia, listens on a random loopback
port, exchanges the one-time code, requests public module/status data, revokes the
temporary device and checks 401. All credentials stay in memory. Only statuses/counts
are printed; source business data is not changed. The repository is private; use the
existing checkout or authenticated GitHub CLI to retrieve this script. A successful
run ends with `success: true`. The deployed service passed this real Chrome flow on
2026-10-21 at 10:16 +08:00 on the owner's MacBook Pro: public modules/status=200,
13 sources, and the revoked temporary device=401. Current running image is
`local/hub-api:3d69313`, including the verified attention copy fix; net/git remain
partial for the source coverage described above.


## Mainline, goals and reviews (phase 5)

The `review` source reads private personal-review GET `/v1/stage` with a 60-second
TTL and the usual source isolation/stale expiry. The `goals` module exposes only the
shared mainline/cycle/goals/review/close shape; failed comment reads mark it partial.
Source status never triggers a fetch. Attention uses this cache for pending daily/weekly
reviews and preclose/awaiting-close cards; IDs remain stable and support dismiss/snooze.
Expired sessions are excluded even when the cached source still says open.

`/api/v1/review/sessions`, detail and preview forward to personal-review, preserving
422 Chinese validation messages/fields and 409 expired. Request bodies are bounded;
no request/body/credential logging. Source keys and internal error fields are discarded.
The raw source bearer lives only in private Hub env; the source verifies a private hash.

Write proxies also expose review finalize, goal comments, cycle close/create and goal
create/publish. They forward once, preserve the source's rules/errors, and invalidate
review cache after success or an uncertain write outcome; dry-run preserves cache.
Source write timeout is 30s. Reads retain the ordinary source deadline/60s TTL.
Cycle creation accepts optional dry_run; successful create/publish replies include status.

Phase-5 release: Hub 1712dfb, source code fd6bd78 (repository main feabd88), 58 Hub
and 80 source tests pass. Authenticated LAN/public reads and stage dry-runs passed.
All original credentials and 11 review jobs were retained. The owner deferred real
App archival; actual Memos writes and Telegram delivery remain unverified. No production
test archive, comment, goal/cycle or test message was created. Full execution/rollback
evidence is in docs/plans/2026-10-21-phase5-nas-execution.md at the repository root.

## Hub v2 network plans

GET/PUT `/api/v1/net/plans` stores up to five unique manual plans as the `net_plans`
configuration document. Successful replacement invalidates the usage cache. Billing
periods include both `period_start` and `period_end`; reset days are limited to 1–28.
A reset on day 1 uses the observed `month_bytes`. The current Usage Monitor HTTP API
only exposes a natural-month total and today's hours, so other reset days return
`used_bytes: null`; usage is never estimated. Every plan uses the same router counter
(for the same period, usage is identical); traffic cannot be assigned to individual
providers. Existing traffic remaining/expiry preferences apply to these manual pools.
Collection gaps still leave the net module partial. An empty plan list produces `pools: []`.
