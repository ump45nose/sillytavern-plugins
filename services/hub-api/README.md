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
The bind directory `/vol2/1000/Docker/hub/data` is the `hub-data` store; it sits under
Duplicati's existing `/source` mount. Source containers are accessed through existing
LAN listeners and require no configuration changes.

Run verification from **this directory**: `uv run pytest`.
