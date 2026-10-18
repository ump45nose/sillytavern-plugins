"""人物与可编辑多人交互归档，旧表保留供一次转换。"""

from alembic import op

from personal_crm.archive.models import metadata

revision = "004_person_archive"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    metadata.drop_all(op.get_bind())
