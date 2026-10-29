"""Bind read-only specialist tasks to private, conversation-scoped sessions."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f3c7209d18aa"
down_revision = "4d9a7b12c5ef"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_specialist_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("agent", sa.String(32), nullable=False),
        sa.Column("origin_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "project_id", "owner_id", "thread_id", "agent"),
    )
    op.create_index("ix_agent_specialist_sessions_workspace_id", "agent_specialist_sessions", ["workspace_id"])
    op.add_column("agent_runs", sa.Column("specialist_session_id", sa.Uuid(), nullable=True))
    op.add_column("agent_runs", sa.Column("specialist_history", JSONB(), nullable=True))
    op.create_foreign_key("fk_agent_runs_specialist_session_id_agent_specialist_sessions", "agent_runs",
                          "agent_specialist_sessions", ["specialist_session_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_agent_runs_specialist_session_id", "agent_runs", ["specialist_session_id"])


def downgrade():
    op.drop_index("ix_agent_runs_specialist_session_id", table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_specialist_session_id_agent_specialist_sessions", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "specialist_history")
    op.drop_column("agent_runs", "specialist_session_id")
    op.drop_index("ix_agent_specialist_sessions_workspace_id", table_name="agent_specialist_sessions")
    op.drop_table("agent_specialist_sessions")
