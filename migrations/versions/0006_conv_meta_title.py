"""Thêm cột title vào conv_meta để user có thể đặt tên cho cuộc trò chuyện.

Revision ID: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conv_meta", sa.Column("title", sa.Text))


def downgrade() -> None:
    op.drop_column("conv_meta", "title")
