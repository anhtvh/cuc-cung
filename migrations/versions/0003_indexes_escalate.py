"""I-01: index messages(user_id, agent_name), usage_log(agent_name), agents(created_by).
I-05: cột escalate_enabled cho agents.

Revision ID: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as sa_inspect
    conn = op.get_bind()
    insp = sa_inspect(conn)

    # I-05: cột escalate_enabled (default 1 = True → không thay đổi hành vi agent hiện tại)
    existing_cols = [c["name"] for c in insp.get_columns("agents")]
    if "escalate_enabled" not in existing_cols:
        with op.batch_alter_table("agents") as batch_op:
            batch_op.add_column(sa.Column("escalate_enabled", sa.Boolean, server_default="1"))

    # I-01: index để tránh full scan khi dữ liệu lớn (if_not_exists cho idempotent)
    existing_indexes = {idx["name"] for idx in insp.get_indexes("messages")}
    if "ix_messages_user_agent" not in existing_indexes:
        op.create_index("ix_messages_user_agent", "messages", ["user_id", "agent_name"])

    existing_usage_idx = {idx["name"] for idx in insp.get_indexes("usage_log")}
    if "ix_usage_log_agent_name" not in existing_usage_idx:
        op.create_index("ix_usage_log_agent_name", "usage_log", ["agent_name"])

    existing_agent_idx = {idx["name"] for idx in insp.get_indexes("agents")}
    if "ix_agents_created_by" not in existing_agent_idx:
        op.create_index("ix_agents_created_by", "agents", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_agents_created_by", "agents")
    op.drop_index("ix_usage_log_agent_name", "usage_log")
    op.drop_index("ix_messages_user_agent", "messages")

    with op.batch_alter_table("agents") as batch_op:
        batch_op.drop_column("escalate_enabled")
