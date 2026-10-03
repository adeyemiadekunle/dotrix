"""workspace skills

Revision ID: 19d1652c9593
Revises: 68afe9d5d466
Create Date: 2026-10-03 01:16:04.141774
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "19d1652c9593"
down_revision: str | None = "68afe9d5d466"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_skills",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_workspace_skills_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_skills_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_skills")),
        sa.UniqueConstraint(
            "workspace_id", "name", name=op.f("uq_workspace_skills_workspace_id_name")
        ),
    )
    op.create_index(
        op.f("ix_workspace_skills_workspace_id"), "workspace_skills", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_skills_workspace_id"), table_name="workspace_skills")
    op.drop_table("workspace_skills")
