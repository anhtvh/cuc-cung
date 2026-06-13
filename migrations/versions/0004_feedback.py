"""Thêm bảng feedback_log cho thumbs up/down trên mỗi câu trả lời.

Revision ID: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text),
        sa.Column("agent_name", sa.Text),
        sa.Column("rating", sa.Integer),          # 1 = tốt, -1 = tệ
        sa.Column("message_preview", sa.Text),    # 100 ký tự đầu câu trả lời
        sa.Column("created_at", sa.Text),
    )
    op.create_index("ix_feedback_agent_name", "feedback_log", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_feedback_agent_name", "feedback_log")
    op.drop_table("feedback_log")
