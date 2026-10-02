"""agent lessons

Revision ID: 4c2fa83f7d22
Revises: 5ef76d56df55
Create Date: 2026-10-02 20:14:16.653063
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4c2fa83f7d22"
down_revision: str | None = "5ef76d56df55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_lessons",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(length=32), nullable=False),
        sa.Column("text", sa.String(length=600), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "rejection",
                "dismissal",
                name="lessonsource",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "proposed",
                "accepted",
                "declined",
                name="lessonstatus",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("proposed_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_agent_lessons_decided_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_agent_lessons_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_id"],
            ["users.id"],
            name=op.f("fk_agent_lessons_proposed_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_lessons_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_lessons")),
    )
    op.create_index(
        op.f("ix_agent_lessons_project_id"), "agent_lessons", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_agent_lessons_workspace_id"), "agent_lessons", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_lessons_workspace_id"), table_name="agent_lessons")
    op.drop_index(op.f("ix_agent_lessons_project_id"), table_name="agent_lessons")
    op.drop_table("agent_lessons")
