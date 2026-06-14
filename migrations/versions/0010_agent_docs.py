"""Bảng agent_docs — registry tài liệu RAG đã upload cho mỗi agent.

Chunk thật nằm ở AgentBase knowledge store (vector). Bảng này chỉ track metadata
(tên file, số chunk, ai upload) để UI list/xoá. Module RAG bật/tắt bằng RAG_ENABLED;
bảng tạo sẵn không ảnh hưởng gì khi RAG tắt.

Revision ID: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_docs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_name", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("chunk_count", sa.Integer),
        sa.Column("status", sa.Text),
        sa.Column("created_by", sa.Text),
        sa.Column("created_at", sa.Text),
    )
    op.create_index("ix_agent_docs_agent", "agent_docs", ["agent_name"])


def downgrade() -> None:
    op.drop_index("ix_agent_docs_agent", table_name="agent_docs")
    op.drop_table("agent_docs")
