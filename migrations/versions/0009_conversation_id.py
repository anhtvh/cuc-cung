"""Thêm conversation_id — tách thread khỏi agent (nhiều cuộc/agent như ChatGPT).

Trước: thread = (user_id, agent_name) → mỗi agent chỉ 1 cuộc.
Sau:   thread = (user_id, conversation_id) → nhiều cuộc độc lập, agent_name chỉ là
       "agent hiện tại của cuộc" (lưu để hiển thị + routing).

Backfill: conversation_id = agent_name cho mọi row cũ → thread cũ giữ nguyên, không mất data.

Revision ID: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # messages: mỗi tin nhắn gắn conversation_id (thread). agent_name giữ lại = agent đã trả lời.
    op.add_column("messages", sa.Column("conversation_id", sa.Text))
    op.execute("UPDATE messages SET conversation_id = agent_name WHERE conversation_id IS NULL")

    # conv_meta: metadata theo conversation_id; agent_name = agent hiện tại của cuộc.
    op.add_column("conv_meta", sa.Column("conversation_id", sa.Text))
    op.execute("UPDATE conv_meta SET conversation_id = agent_name WHERE conversation_id IS NULL")

    # Unique key cũ (user_id, agent_name) chặn nhiều cuộc/agent → thay bằng (user_id, conversation_id).
    op.drop_index("ix_conv_meta_user_agent", table_name="conv_meta")
    op.create_index("ix_conv_meta_user_conv", "conv_meta", ["user_id", "conversation_id"], unique=True)
    # Index tra cứu messages theo thread.
    op.create_index("ix_messages_user_conv", "messages", ["user_id", "conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_user_conv", table_name="messages")
    op.drop_index("ix_conv_meta_user_conv", table_name="conv_meta")
    op.create_index("ix_conv_meta_user_agent", "conv_meta", ["user_id", "agent_name"], unique=True)
    op.drop_column("conv_meta", "conversation_id")
    op.drop_column("messages", "conversation_id")
