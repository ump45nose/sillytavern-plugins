"""CRM 迁移、健康与备份维护入口。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .settings import Settings


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["migrate", "migrate-legacy", "repair-wechat", "integrity", "backup"]
    )
    parser.add_argument("path", nargs="?")
    parser.add_argument("--accounts", default="wechat-main,legacy")
    parser.add_argument("--backup")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "migrate":
        from sqlalchemy.engine import make_url

        url = make_url(settings.database_url)
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)
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
    elif args.command == "repair-wechat":
        from personal_crm.archive.repair import repair_wechat

        if not args.path:
            parser.error("repair-wechat requires a directory JSON path")
        print(
            json.dumps(
                repair_wechat(
                    archive,
                    json.loads(Path(args.path).read_text()),
                    accounts=args.accounts.split(","),
                    backup=args.backup,
                    apply=args.apply,
                )
            )
        )
    elif args.command == "integrity":
        print(archive.integrity_check())
    else:
        if not args.path:
            parser.error("backup requires a destination path")
        if archive.engine.dialect.name != "sqlite":
            parser.error("PostgreSQL: use pg_dump before migration")
        import sqlite3

        target = Path(args.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.engine.connect() as c, sqlite3.connect(target) as destination:
            c.connection.driver_connection.backup(destination)
        target.chmod(0o600)
        print(target)
    return 0
