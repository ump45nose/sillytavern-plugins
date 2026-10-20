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
