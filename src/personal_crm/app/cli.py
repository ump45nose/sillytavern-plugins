"""CRM 数据库升级与完整性检查。"""

from __future__ import annotations

import argparse
from pathlib import Path

from .settings import Settings


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["migrate", "integrity"])
    args = parser.parse_args(argv)
    settings = Settings()
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
    print(archive.integrity_check())
    return 0
