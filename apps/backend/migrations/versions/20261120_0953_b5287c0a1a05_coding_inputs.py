"""Coding inputs: messages a person sends a session while Kai works, to steer the running turn or queue the next.

Revision ID: b5287c0a1a05
Revises: e8d7b3241083
Create Date: 2026-11-20 09:53:12.083537
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5287c0a1a05"
down_revision: str | None = "e8d7b3241083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coding_inputs",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("delivered_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "steer",
                "queue",
                name="codinginputkind",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "sending",
                "accepted",
                "delivered",
                "cancelled",
                "rejected",
                name="codinginputstatus",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["delivered_run_id"],
            ["coding_runs.id"],
            name=op.f("fk_coding_inputs_delivered_run_id_coding_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_coding_inputs_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_coding_inputs_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["coding_runs.id"],
            name=op.f("fk_coding_inputs_run_id_coding_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_coding_inputs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coding_inputs")),
        sa.UniqueConstraint(
            "workspace_id",
            "owner_id",
            "client_id",
            name=op.f("uq_coding_inputs_workspace_id_owner_id_client_id"),
        ),
    )
    op.create_index(
        op.f("ix_coding_inputs_project_id"), "coding_inputs", ["project_id"], unique=False
    )
    op.create_index(op.f("ix_coding_inputs_run_id"), "coding_inputs", ["run_id"], unique=False)
    op.create_index(
        op.f("ix_coding_inputs_session_id"), "coding_inputs", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_coding_inputs_workspace_id"), "coding_inputs", ["workspace_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_coding_inputs_workspace_id"), table_name="coding_inputs")
    op.drop_index(op.f("ix_coding_inputs_session_id"), table_name="coding_inputs")
    op.drop_index(op.f("ix_coding_inputs_run_id"), table_name="coding_inputs")
    op.drop_index(op.f("ix_coding_inputs_project_id"), table_name="coding_inputs")
    op.drop_table("coding_inputs")
