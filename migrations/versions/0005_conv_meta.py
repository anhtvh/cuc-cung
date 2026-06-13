"""Thêm bảng conv_meta: lưu conversation metadata độc lập với memory backend.

Giải quyết vấn đề: khi dùng MEMORY_BACKEND=agentbase, /history trả rỗng vì
messages không ghi vào SQLite. conv_meta luôn ghi bất kể backend là gì.

Revision ID: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conv_meta",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("agent_name", sa.Text, nullable=False),
        sa.Column("last_text", sa.Text),
        sa.Column("updated_at", sa.Text),
    )
    op.create_index("ix_conv_meta_user_agent", "conv_meta", ["user_id", "agent_name"], unique=True)
    op.create_index("ix_conv_meta_updated", "conv_meta", ["user_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_conv_meta_updated", "conv_meta")
    op.drop_index("ix_conv_meta_user_agent", "conv_meta")
    op.drop_table("conv_meta")
