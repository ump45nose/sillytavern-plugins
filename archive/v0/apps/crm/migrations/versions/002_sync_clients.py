"""增加跨客户端消息去重索引和连接器状态表。

Revision ID: 002_sync_clients
Revises: 001_initial
"""

import sqlalchemy as sa
from alembic import context, op

revision = "002_sync_clients"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """升级已有生产库；兼容初始迁移使用当前 ORM 元数据创建的新库。"""

    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    columns = [] if inspector is None else inspector.get_columns("interactions")
    if not any(column["name"] == "source_message_key" for column in columns):
        op.add_column("interactions", sa.Column("source_message_key", sa.String(64)))
    indexes = [] if inspector is None else inspector.get_indexes("interactions")
    if not any(index["name"] == "uq_interaction_source_message" for index in indexes):
        op.create_index(
            "uq_interaction_source_message",
            "interactions",
            ["source_type", "source_message_key"],
            unique=True,
        )
    if inspector is None or not inspector.has_table("sync_clients"):
        op.create_table(
            "sync_clients",
            sa.Column("source", sa.String(80), primary_key=True),
            sa.Column("client_id", sa.String(80), primary_key=True),
            sa.Column("last_batch_id", sa.String(36)),
            sa.Column("synced_through", sa.DateTime()),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("accepted_total", sa.Integer(), nullable=False),
            sa.Column("duplicate_total", sa.Integer(), nullable=False),
        )


def downgrade() -> None:
    """回退技术状态和稳定身份字段，保留四张业务表及其数据。"""

    op.drop_table("sync_clients")
    op.drop_index("uq_interaction_source_message", table_name="interactions")
    op.drop_column("interactions", "source_message_key")
