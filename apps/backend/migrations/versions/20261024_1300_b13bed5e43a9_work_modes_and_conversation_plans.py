"""Work modes on agent runs, conversation plans, and the conversation a coding run came from.

Revision ID: b13bed5e43a9
Revises: 8e3a6c2b4d19
Create Date: 2026-10-24 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b13bed5e43a9"
down_revision: str | None = "8e3a6c2b4d19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_plans",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tasks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("open_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_conversation_plans_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_conversation_plans_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_conversation_plans_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_plans")),
        sa.UniqueConstraint(
            "thread_id", "version", name=op.f("uq_conversation_plans_thread_id_version")
        ),
    )
    op.create_index(
        op.f("ix_conversation_plans_project_id"), "conversation_plans", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_conversation_plans_thread_id"), "conversation_plans", ["thread_id"], unique=False
    )
    op.create_index(
        op.f("ix_conversation_plans_workspace_id"),
        "conversation_plans",
        ["workspace_id"],
        unique=False,
    )
    op.add_column(
        "agent_runs",
        sa.Column(
            "work_mode",
            sa.Enum(
                "discuss",
                "plan",
                "build",
                "review",
                name="workmode",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=True,
        ),
    )
    op.add_column("coding_runs", sa.Column("thread_id", sa.Uuid(), nullable=True))
    op.add_column("coding_runs", sa.Column("plan_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_coding_runs_thread_id"), "coding_runs", ["thread_id"], unique=False)
    op.create_foreign_key(
        op.f("fk_coding_runs_plan_id_conversation_plans"),
        "coding_runs",
        "conversation_plans",
        ["plan_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_coding_runs_plan_id_conversation_plans"), "coding_runs", type_="foreignkey"
    )
    op.drop_index(op.f("ix_coding_runs_thread_id"), table_name="coding_runs")
    op.drop_column("coding_runs", "plan_id")
    op.drop_column("coding_runs", "thread_id")
    op.drop_column("agent_runs", "work_mode")
    op.drop_index(op.f("ix_conversation_plans_workspace_id"), table_name="conversation_plans")
    op.drop_index(op.f("ix_conversation_plans_thread_id"), table_name="conversation_plans")
    op.drop_index(op.f("ix_conversation_plans_project_id"), table_name="conversation_plans")
    op.drop_table("conversation_plans")
