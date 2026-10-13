#!/usr/bin/env python3
"""Read Hub run metadata inside its existing container; never initialize Store."""

from datetime import datetime, timezone
import os

from sqlalchemy import create_engine, func, select, text

from personal_data_hub.contracts import canonical
from personal_data_hub.runner import configuration
from personal_data_hub.storage import runs


def snapshot():
    config = configuration()
    settings = {
        source: {key: value for key, value in item.items()
                 if key in ("enabled", "collection_mode", "interval_seconds")}
        for source, item in config["sources"].items()
    }
    selected = [source for source, item in settings.items()
                if item.get("enabled", True) and item.get("collection_mode") != "push"]
    now = datetime.now(timezone.utc)
    result = {"checked_at": now, "sources": settings, "latest_runs": {}, "latest_finished_runs": {}}
    url = config.get("database_url") or os.environ.get("HUB_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        raise RuntimeError("hub_postgresql_configuration_missing")
    engine = create_engine(url, connect_args={
        "connect_timeout": 10,
        "options": "-c statement_timeout=15000 -c default_transaction_read_only=on",
    })
    try:
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
            ranked = select(
                runs.c.source, runs.c.status, runs.c.error, runs.c.started_at, runs.c.ended_at,
                func.row_number().over(
                    partition_by=runs.c.source,
                    order_by=(runs.c.started_at.desc(), runs.c.id.desc()),
                ).label("position"),
            ).where(runs.c.source.in_(selected)).subquery()
            for row in connection.execute(select(ranked).where(ranked.c.position == 1)).mappings():
                item = dict(row)
                item.pop("position")
                result["latest_runs"][item["source"]] = item
            finished = select(
                runs.c.source, runs.c.status, runs.c.error, runs.c.started_at, runs.c.ended_at,
                func.row_number().over(
                    partition_by=runs.c.source,
                    order_by=(runs.c.started_at.desc(), runs.c.id.desc()),
                ).label("position"),
            ).where(runs.c.source.in_(selected), runs.c.ended_at.is_not(None)).subquery()
            for row in connection.execute(select(finished).where(finished.c.position == 1)).mappings():
                item = dict(row)
                item.pop("position")
                result["latest_finished_runs"][item["source"]] = item
    finally:
        engine.dispose()
    return result


if __name__ == "__main__":
    print(canonical(snapshot()))
