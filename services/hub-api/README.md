# hub-api

Python 3.12 thin backend. Source business records remain in their owning applications.
Only devices, preferences/layout, subscriptions and attention handling are durable;
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
so one API failure does not remove the other module. All other not-yet-integrated
sources explicitly report `unconfigured`.

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
