"""Thêm cột salutation (xưng hô anh/chị) cho user.

Master hỏi 1 lần rồi lưu — agent dùng để xưng 'em' gọi 'anh'/'chị' thay vì 'bạn'.

Revision ID: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable: chưa biết → agent fallback 'anh/chị', master sẽ hỏi.
    op.add_column("users", sa.Column("salutation", sa.Text))


def downgrade() -> None:
    op.drop_column("users", "salutation")
