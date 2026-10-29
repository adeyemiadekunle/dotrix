"""Bind experimental runtime sessions to their private agent runs."""
import sqlalchemy as sa
from alembic import op

revision = "6cf58b7d214a"
down_revision = "7d91e4f3a201"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_runtime_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("runtime", sa.String(32), nullable=False),
        sa.Column("runtime_version", sa.String(80), nullable=False),
        sa.Column("config_digest", sa.String(64), nullable=False),
        sa.Column("session_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id"),
        sa.UniqueConstraint("runtime", "session_id"),
    )
    op.create_index("ix_agent_runtime_bindings_workspace_id", "agent_runtime_bindings", ["workspace_id"])


def downgrade():
    op.drop_index("ix_agent_runtime_bindings_workspace_id", table_name="agent_runtime_bindings")
    op.drop_table("agent_runtime_bindings")
