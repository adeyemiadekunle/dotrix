"""Persist private chat steering and queued follow-ups."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "52a9e71bc304"
down_revision = "f3c7209d18aa"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_chat_inputs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("delivered_run_id", sa.Uuid(), sa.ForeignKey("agent_runs.id", ondelete="SET NULL")),
        sa.Column("error", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "project_id", "owner_id", "client_id"),
    )
    op.create_index("ix_agent_chat_inputs_workspace_id", "agent_chat_inputs", ["workspace_id"])
    op.create_index("ix_agent_chat_inputs_thread_id", "agent_chat_inputs", ["thread_id"])
    op.create_index("ix_agent_chat_inputs_run_id", "agent_chat_inputs", ["run_id"])
    op.create_index("ix_agent_chat_inputs_due", "agent_chat_inputs", ["kind", "status", "created_at", "id"])


def downgrade():
    op.drop_table("agent_chat_inputs")
