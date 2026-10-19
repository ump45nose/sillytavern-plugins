"""Alembic 在线与离线迁移入口。"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from personal_crm.storage.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
config.set_main_option(
    "sqlalchemy.url", config.attributes.get("configured_database_url") or os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
)
from personal_crm.archive.models import metadata as archive_metadata
target_metadata = [Base.metadata, archive_metadata]


def run_migrations_offline() -> None:
    """生成不连接数据库的迁移 SQL。"""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
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
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        # SQLAlchemy 2 会让 PRAGMA 触发隐式事务；先提交，避免 Alembic 版本号随连接回滚。
        connection.commit()
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
