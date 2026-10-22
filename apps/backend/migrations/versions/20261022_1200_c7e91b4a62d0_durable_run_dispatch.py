"""durable run dispatch

Revision ID: c7e91b4a62d0
Revises: 8b41e0c7d2f3
Create Date: 2026-10-22 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c7e91b4a62d0"
down_revision: str | None = "8b41e0c7d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("agent_runs", "coding_runs"):
        op.add_column(table, sa.Column(
            "dispatch_generation", sa.Integer(), server_default="0", nullable=False,
        ))
    op.create_table(
        "run_dispatches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("coding_run_id", sa.Uuid(), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("queue_name", sa.String(128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("delivery_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(100), nullable=True),
        sa.CheckConstraint(
            "(agent_run_id IS NOT NULL AND coding_run_id IS NULL) OR "
            "(agent_run_id IS NULL AND coding_run_id IS NOT NULL)",
            name=op.f("ck_run_dispatches_one_run_target"),
        ),
        sa.CheckConstraint("generation > 0", name=op.f("ck_run_dispatches_positive_generation")),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"],
                                name=op.f("fk_run_dispatches_workspace_id_workspaces"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"],
                                name=op.f("fk_run_dispatches_agent_run_id_agent_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["coding_run_id"], ["coding_runs.id"],
                                name=op.f("fk_run_dispatches_coding_run_id_coding_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_dispatches")),
        sa.UniqueConstraint("agent_run_id", "generation", name=op.f("uq_run_dispatches_agent_run_id_generation")),
        sa.UniqueConstraint("coding_run_id", "generation", name=op.f("uq_run_dispatches_coding_run_id_generation")),
    )
    op.create_index("ix_run_dispatches_workspace_id", "run_dispatches", ["workspace_id"])
    op.create_index("ix_run_dispatches_due", "run_dispatches", [
        "queue_name", "accepted_at", "discarded_at", "next_attempt_at",
    ])


def downgrade() -> None:
    op.drop_index("ix_run_dispatches_due", table_name="run_dispatches")
    op.drop_index("ix_run_dispatches_workspace_id", table_name="run_dispatches")
    op.drop_table("run_dispatches")
    for table in ("agent_runs", "coding_runs"):
        op.drop_column(table, "dispatch_generation")
