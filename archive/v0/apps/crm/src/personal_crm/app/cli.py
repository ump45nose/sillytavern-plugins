"""CRM 迁移、健康与备份维护入口。"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from .settings import Settings


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "migrate-legacy", "integrity", "backup"])
    parser.add_argument("path", nargs="?")
    args = parser.parse_args(argv)
    settings = Settings()
    # The integrated service's configured PostgreSQL takes precedence over its legacy SQLite env.
    if os.environ.get("HUB_CONFIG"):
        hub = json.loads(Path(os.environ["HUB_CONFIG"]).read_text())
        settings.database_url = hub.get("database_url") or os.environ["HUB_DATABASE_URL"]
        settings.crm_asset_root = hub["asset_root"]
    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        config = Config()
        location = Path(__file__).resolve().parents[1] / "migrations"
        if not location.exists():
            location = Path(__file__).resolve().parents[3] / "migrations"
        config.set_main_option("script_location", str(location))
        config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
        config.attributes["configured_database_url"] = settings.database_url
        command.upgrade(config, "head")
        print("migrated")
        return 0
    from personal_crm.archive import Archive

    archive = Archive(
        settings.database_url,
        settings.crm_asset_root,
        gap_minutes=settings.wechat_interaction_gap_minutes,
        create_schema=False,
    )
    if args.command == "migrate-legacy":
        from personal_crm.archive.migration import migrate_legacy

        print(json.dumps(migrate_legacy(archive)))
    elif args.command == "integrity":
        print(archive.integrity_check())
    else:
        if not args.path:
            parser.error("backup requires a destination path")
        if archive.engine.dialect.name != "sqlite":
            parser.error(
                "PostgreSQL: use the existing hub backup command / pg_dump before migration"
            )
        import sqlite3

        target = Path(args.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.engine.connect() as c, sqlite3.connect(target) as destination:
            c.connection.driver_connection.backup(destination)
        target.chmod(0o600)
        print(target)
    return 0
