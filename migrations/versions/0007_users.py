"""Thêm bảng users cho auth (Google OAuth + admin password).

Revision ID: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Text, primary_key=True),      # Google sub hoặc "admin_<email>"
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("name", sa.Text),
        sa.Column("picture", sa.Text),
        sa.Column("role", sa.Text, nullable=False, server_default="user"),  # user | admin
        sa.Column("hashed_password", sa.Text),            # chỉ admin
        sa.Column("created_at", sa.Text),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", "users")
    op.drop_table("users")
