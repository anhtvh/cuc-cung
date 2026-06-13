"""Schema ban đầu (AGENT_HUB_DESIGN.md §4) + hook org_id/visibility/identity_ref.

Revision ID: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("connectors", sa.Text, server_default="[]"),
        sa.Column("domain", sa.Text),
        sa.Column("status", sa.Text, server_default="private"),
        sa.Column("pending_changes", sa.Text),
        sa.Column("visibility", sa.Text, server_default="company"),
        sa.Column("identity_ref", sa.Text),
        sa.Column("org_id", sa.Text),
        sa.Column("created_by", sa.Text),
        sa.Column("reviewed_by", sa.Text),
        sa.Column("review_note", sa.Text),
        sa.Column("created_at", sa.Text),
        sa.Column("updated_at", sa.Text),
    )
    op.create_table(
        "skills",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("domain", sa.Text),
        sa.Column("status", sa.Text, server_default="private"),
        sa.Column("pending_changes", sa.Text),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("org_id", sa.Text),
        sa.Column("created_by", sa.Text),
        sa.Column("reviewed_by", sa.Text),
        sa.Column("review_note", sa.Text),
        sa.Column("created_at", sa.Text),
        sa.Column("updated_at", sa.Text),
    )
    op.create_table(
        "agent_skills",
        sa.Column("agent_name", sa.Text, sa.ForeignKey("agents.name"), primary_key=True),
        sa.Column("skill_name", sa.Text, sa.ForeignKey("skills.name"), primary_key=True),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text),
        sa.Column("agent_name", sa.Text),
        sa.Column("role", sa.Text),
        sa.Column("content", sa.Text),
        sa.Column("created_at", sa.Text),
    )
    op.create_index("ix_messages_user_agent", "messages", ["user_id", "agent_name"])
    op.create_table(
        "usage_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.Text),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("created_at", sa.Text),
    )


def downgrade() -> None:
    op.drop_table("usage_log")
    op.drop_index("ix_messages_user_agent", table_name="messages")
    op.drop_table("messages")
    op.drop_table("agent_skills")
    op.drop_table("skills")
    op.drop_table("agents")
