"""Cột web_search_enabled cho agents — per-agent toggle web-search always-on.

Agent closed-domain (FAQ/Deals/Docs Zalopay) đặt False → engine không cấp web-search,
buộc bám nguồn chính thức của agent (chống đi search ngoài rồi bịa). Default 1 = True
→ không đổi hành vi agent hiện tại.

Revision ID: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    conn = op.get_bind()
    insp = sa_inspect(conn)
    existing_cols = [c["name"] for c in insp.get_columns("agents")]
    if "web_search_enabled" not in existing_cols:
        with op.batch_alter_table("agents") as batch_op:
            batch_op.add_column(sa.Column("web_search_enabled", sa.Boolean, server_default="1"))


def downgrade() -> None:
    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("web_search_enabled")
