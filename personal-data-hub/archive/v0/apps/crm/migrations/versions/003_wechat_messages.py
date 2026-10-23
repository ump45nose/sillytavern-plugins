"""原样保存微信源消息，兼容现有摘要及稳定消息身份。"""

import sqlalchemy as sa
from alembic import context, op

revision = "003_wechat_messages"
down_revision = "002_sync_clients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = None if context.is_offline_mode() else sa.inspect(op.get_bind())
    if inspector is None or not any(c["name"] == "message" for c in inspector.get_columns("interactions")):
        op.add_column("interactions", sa.Column("message", sa.JSON(none_as_null=True), nullable=True))


def downgrade() -> None:
    op.drop_column("interactions", "message")
