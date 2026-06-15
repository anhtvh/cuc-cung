"""Bổ sung cột observability cho usage_log (I-05).

Thêm latency_ms (độ trễ mỗi lượt), tool_calls (số tool-call), stop_reason (lý do dừng)
để dashboard admin soi latency/tool-rate/tỉ lệ lỗi per-agent. Nullable → row cũ không vỡ.

Revision ID: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usage_log", sa.Column("latency_ms", sa.Integer))
    op.add_column("usage_log", sa.Column("tool_calls", sa.Integer))
    op.add_column("usage_log", sa.Column("stop_reason", sa.Text))


def downgrade() -> None:
    op.drop_column("usage_log", "stop_reason")
    op.drop_column("usage_log", "tool_calls")
    op.drop_column("usage_log", "latency_ms")
