"""Thêm id UUID, tagline, slug cho agents; id UUID cho skills.

Revision ID: 0002
"""

import re
import unicodedata
import uuid as _uuid

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_str.lower()).strip("-")
    return slug or "agent"


def upgrade() -> None:
    # --- agents: thêm id, tagline, slug ---
    with op.batch_alter_table("agents") as batch_op:
        batch_op.add_column(sa.Column("id", sa.Text))
        batch_op.add_column(sa.Column("tagline", sa.Text))
        batch_op.add_column(sa.Column("slug", sa.Text))

    conn = op.get_bind()
    for (name,) in conn.execute(sa.text("SELECT name FROM agents")).fetchall():
        conn.execute(
            sa.text("UPDATE agents SET id = :id, slug = :slug WHERE name = :name"),
            {"id": str(_uuid.uuid4()), "slug": _slugify(name), "name": name},
        )

    with op.batch_alter_table("agents", recreate="always") as batch_op:
        batch_op.create_unique_constraint("uq_agents_id", ["id"])
        batch_op.create_unique_constraint("uq_agents_slug", ["slug"])

    # --- skills: thêm id ---
    with op.batch_alter_table("skills") as batch_op:
        batch_op.add_column(sa.Column("id", sa.Text))

    for (name,) in conn.execute(sa.text("SELECT name FROM skills")).fetchall():
        conn.execute(
            sa.text("UPDATE skills SET id = :id WHERE name = :name"),
            {"id": str(_uuid.uuid4()), "name": name},
        )

    with op.batch_alter_table("skills", recreate="always") as batch_op:
        batch_op.create_unique_constraint("uq_skills_id", ["id"])


def downgrade() -> None:
    with op.batch_alter_table("skills", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_skills_id", type_="unique")
        batch_op.drop_column("id")

    with op.batch_alter_table("agents", recreate="always") as batch_op:
        batch_op.drop_constraint("uq_agents_slug", type_="unique")
        batch_op.drop_constraint("uq_agents_id", type_="unique")
        batch_op.drop_column("slug")
        batch_op.drop_column("tagline")
        batch_op.drop_column("id")
