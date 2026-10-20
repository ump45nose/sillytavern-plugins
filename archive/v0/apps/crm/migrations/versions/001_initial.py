"""创建四张个人 CRM 核心表。

Revision ID: 001_initial
Revises:
"""

from alembic import op

from personal_crm.storage.models import Base

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建与 ORM 元数据一致的初始表和索引。"""

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """按依赖顺序删除初始表。"""

    Base.metadata.drop_all(bind=op.get_bind())
