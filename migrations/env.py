"""Alembic 在线与离线迁移入口。"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from personal_crm.archive.models import metadata as archive_metadata

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
config.set_main_option(
    "sqlalchemy.url",
    (
        config.attributes.get("configured_database_url")
        or os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    ).replace("%", "%%"),
)

target_metadata = archive_metadata


def run_migrations_offline() -> None:
    """生成不连接数据库的迁移 SQL。"""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """连接目标数据库并执行迁移。"""

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=lambda name, type_, parent: (
                type_ != "table" or name in archive_metadata.tables
            ),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
