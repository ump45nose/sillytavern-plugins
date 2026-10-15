"""旧版本升级标记；新安装不再创建停用业务表。"""

revision = "003_wechat_messages"
down_revision = "002_sync_clients"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
