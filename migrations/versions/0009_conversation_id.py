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
    # IDEMPOTENT: SQLite alembic chạy non-transactional DDL → migration có thể nửa-áp-dụng rồi
    # crash (vd drop_index 1 index không tồn tại) khiến lần chạy sau lỗi "duplicate column".
    # Mỗi bước dưới đây đều kiểm tra trạng thái trước → re-run an toàn trên DB nửa-áp-dụng.
    bind = op.get_bind()
    insp = sa.inspect(bind)

    def _cols(table):
        return {c["name"] for c in insp.get_columns(table)}

    def _indexes(table):
        return {i["name"] for i in insp.get_indexes(table)}

    # messages: cột conversation_id (thread) — agent_name giữ lại = agent đã trả lời.
    if "conversation_id" not in _cols("messages"):
        op.add_column("messages", sa.Column("conversation_id", sa.Text))
    op.execute("UPDATE messages SET conversation_id = agent_name WHERE conversation_id IS NULL")

    # conv_meta: metadata theo conversation_id; agent_name = agent hiện tại của cuộc.
    if "conversation_id" not in _cols("conv_meta"):
        op.add_column("conv_meta", sa.Column("conversation_id", sa.Text))
    op.execute("UPDATE conv_meta SET conversation_id = agent_name WHERE conversation_id IS NULL")

    # Thay unique key cũ (user_id, agent_name) → (user_id, conversation_id). IF EXISTS/NOT EXISTS
    # để an toàn dù index nguồn tạo bằng migration hay create_all.
    op.execute("DROP INDEX IF EXISTS ix_conv_meta_user_agent")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_conv_meta_user_conv ON conv_meta (user_id, conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_messages_user_conv ON messages (user_id, conversation_id)")


def downgrade() -> None:
    op.drop_index("ix_messages_user_conv", table_name="messages")
    op.drop_index("ix_conv_meta_user_conv", table_name="conv_meta")
    op.create_index("ix_conv_meta_user_agent", "conv_meta", ["user_id", "agent_name"], unique=True)
    op.drop_column("conv_meta", "conversation_id")
    op.drop_column("messages", "conversation_id")
