"""旧版本升级标记；新安装不再创建停用业务表。"""

revision = "002_sync_clients"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
